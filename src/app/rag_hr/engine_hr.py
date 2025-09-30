import os, time, re, unicodedata
from typing import Tuple, List, Dict, Any, Optional
from langchain_core.documents import Document

from .config_hr import (
    # cấu hình chung
    MAX_CHARS_CTX_HR, GEMINI_MODEL_ANSWER_HR, PROFILE_HR, DATA_DIR_HR,
    STRIP_CITATIONS_HR, METRICS_HR,

    # full-copy & nguồn
    ORG_FULLCOPY_HR, FORM_FULLCOPY_HR, JD_FULLCOPY_HR,
    ORG_SOURCE_HINT_HR, SOURCE_REGISTRY_PATH, STRICT_SOURCE_MATCH_HR,

    # QE
    USE_QR_LLM_HR, QR_LLM_MODEL_HR, QR_NUM_ALIASES_HR,
    USE_PRF_HR, PRF_K_SEM_HR, PRF_NGRAMS_HR, PRF_TOP_PHRASES_HR, PRF_MIN_LEN_CHARS_HR,
    PHRASE_BOOST_TIMES_HR,

    # mini-LLM header
    MINI_LLM_ON_FULLCOPY_HR, MINI_LLM_TASK_HR, MINI_LLM_TASK_ORG_HR, MINI_LLM_MAXTOK_HR,
)

from .prompts_hr import get_system_prompt
from .postprocess import strip_citations, cleanup_org_answer
from .hybrid_hr import load_vs, hybrid_retrieve, build_lex_query
from .rerank_hr import rerank
from .intent_router_hr import classify_intent
from .registry_hr import get_by_path, verify_hash_if_present, pick_best_from_scored

_LAST: Dict[str, Any] = {"question": "", "answer": "", "trace": []}

# ----------------------------- #
#            HELPERS            #
# ----------------------------- #

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _vn_norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-zA-Z0-9 \n]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

ORG_PATTERNS = [
    r"\bsơ\s*đồ\s*tổ\s*chức\b", r"\bsơ\s*đồ\s*nhân\s*sự\b", r"\bsơ\s*đồ\s*nhân\s*viên\b",
    r"\bsơ\s*đồ\s*phòng\s*ban\b", r"\bbiểu\s*đồ\s*nhân\s*sự\b", r"\bcơ\s*cấu\s*tổ\s*chức\b",
    r"\bcơ\s*cấu\s*nhân\s*sự\b", r"\borg(?:anizational)?\s*chart\b",
    r"\bstaff(?:ing)?\s*(?:chart|structure)\b", r"\bteam\s*structure\b", r"\bsơ\s*đồ\s*công\s*ty\b",
]
JD_PATTERNS = [r"\bjd\b", r"\bmô\s*tả\s*công\s*việc\b", r"\bjob\s*description\b", r"\bmtcv\b"]
SOP_PATTERNS = [r"\bquy\s*trình\b", r"\bquy\s*trinh\b", r"\bprocess\b", r"\bprocedure\b", r"\bsop\b"]

def is_org_request(question: str) -> bool:
    return any(re.search(p, _norm(question)) for p in ORG_PATTERNS)

def is_jd_request(question: str) -> bool:
    return any(re.search(p, _norm(question)) for p in JD_PATTERNS)

def is_sop_request(question: str) -> bool:
    return any(re.search(p, _norm(question)) for p in SOP_PATTERNS)

def _candidate_paths(source_rel: str) -> List[str]:
    if not source_rel: return []
    paths = [
        os.path.join(DATA_DIR_HR, source_rel),
        os.path.join(DATA_DIR_HR, source_rel.replace("\\", os.sep)),
    ]
    base = os.path.basename(source_rel)
    for root, _, files in os.walk(DATA_DIR_HR):
        for fn in files:
            if fn == base:
                paths.append(os.path.join(root, fn))
    uniq, seen = [], set()
    for p in paths:
        ab = os.path.abspath(p)
        if ab not in seen and os.path.isfile(ab):
            seen.add(ab); uniq.append(ab)
    return uniq

def read_full_source_text(source_rel: str) -> Optional[str]:
    for full in _candidate_paths(source_rel):
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            continue
    return None

def _normalize_raw(s: str) -> str:
    if not s: return s
    s = s.replace("\u0000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def build_context(pairs: List[Tuple[Document, float]], max_chars: int = MAX_CHARS_CTX_HR) -> str:
    blocks, used = [], 0
    for d, _ in pairs:
        meta = d.metadata or {}
        tag = f"[{meta.get('source','?')}|{meta.get('chunk_id',-1)}]"
        text = (d.page_content or "").strip()
        piece = (f"{tag}\n{text}\n").strip() + "\n"
        if used + len(piece) > max_chars and blocks:
            break
        blocks.append(piece); used += len(piece)
    return "\n---\n".join(blocks)

def _make_trace(ranked: List[Tuple[Document,float]]) -> List[Dict[str,Any]]:
    out=[]
    for d, s in ranked:
        m = d.metadata or {}
        out.append({
            "source": m.get("source","?"),
            "chunk_id": m.get("chunk_id",-1),
            "score": float(s) if s is not None else None,
            "text": d.page_content
        })
    return out

# ----------------------------- #
#       PICK SOURCE (ORG/SOP)   #
# ----------------------------- #

def pick_org_source(ranked_pairs: List[Tuple[Document,float]]) -> Optional[str]:
    # 1) Ưu tiên tên file gợi ý "tổ chức", "tree", "org_chart"
    for d, _ in ranked_pairs:
        src = (d.metadata or {}).get("source", "") or ""
        sn = _norm(src)
        if any(k in sn for k in ["so_do_to_chuc", "to_chuc_nhan_vien", "to_chuc", "tree", "org_chart"]):
            return src
    # 2) Ưu tiên nội dung có cụm "sơ đồ tổ chức"
    for d, _ in ranked_pairs:
        if "sơ đồ tổ chức" in _norm(d.page_content) or "organizational chart" in _norm(d.page_content):
            return (d.metadata or {}).get("source")
    # 3) fallback: lấy source của doc top-1
    return (ranked_pairs[0][0].metadata or {}).get("source") if ranked_pairs else None

def pick_sop_source(ranked_pairs: List[Tuple[Document,float]]) -> Optional[str]:
    for d, _ in ranked_pairs:
        src = (d.metadata or {}).get("source", "") or ""
        sn = _norm(src)
        if any(k in sn for k in ["quy_trinh", "quy trinh", "process", "procedure", "sop"]):
            return src
    for d, _ in ranked_pairs:
        if any(k in _norm(d.page_content) for k in ["quy trình", "quy trinh", "sop"]):
            return (d.metadata or {}).get("source")
    return (ranked_pairs[0][0].metadata or {}).get("source") if ranked_pairs else None

# ----------------------------- #
#           JD HELPERS          #
# ----------------------------- #

def _extract_title(text: str) -> str:
    if not text: return ""
    head = (text[:1200] or "")
    m = re.search(r"(?im)^\s*vị\s*trí\s*:\s*(.+)$", head)
    if m: return m.group(1).strip()
    for line in head.splitlines():
        l = line.strip()
        if re.search(r"(nhân\s*viên|chuyên\s*viên|engineer|intern|tts|it)", _vn_norm(l)):
            return l
    return ""

def _title_sim(a: str, b: str) -> float:
    A = set(_vn_norm(a).split())
    B = set(_vn_norm(b).split())
    if not A or not B: return 0.0
    inter = len(A & B); union = len(A | B)
    return inter / union if union else 0.0

def _guess_title_for_doc(d: Document) -> str:
    t = _extract_title(d.page_content or "")
    if t: return t
    src = ((d.metadata or {}).get("source") or "").split("\\")[-1].split("/")[-1]
    name = re.sub(r"[-_.]+", " ", src)
    return name

TITLE_BONUS_ALPHA = float(os.environ.get("TITLE_BONUS_ALPHA_HR", "0.6"))
PENALTY_TTS = float(os.environ.get("PENALTY_TTS_HR", "0.4"))
PENALTY_CRM = float(os.environ.get("PENALTY_CRM_HR", "0.3"))

def _jd_reweight(question: str, ranked_pairs: List[Tuple[Document, float]]) -> List[Tuple[Document, float]]:
    qn = _vn_norm(question)
    q_mentions_tts = any(k in qn for k in ("tts", "thuc tap", "thực tập", "intern"))
    q_mentions_crm = "crm" in qn

    out = []
    for d, base in ranked_pairs:
        title = _guess_title_for_doc(d)
        sim = _title_sim(question, title)  # 0..1
        score = (base or 0.0) + TITLE_BONUS_ALPHA * sim

        srcn = _vn_norm((d.metadata or {}).get("source", "")) + " " + _vn_norm(title)
        if (("tts" in srcn or "thuc tap" in srcn or "thuc tap sinh" in srcn or "intern" in srcn) and not q_mentions_tts):
            score -= PENALTY_TTS
        if (("crm" in srcn or "application engineer" in srcn) and not q_mentions_crm):
            score -= PENALTY_CRM

        out.append((d, score))
    out.sort(key=lambda x: x[1], reverse=True)
    return out

def _merge_chunks_same_source(pairs: List[Tuple[Document, float]], source: str, max_chars: int) -> str:
    items = []
    for d, _ in pairs:
        if (d.metadata or {}).get("source") == source:
            items.append((int((d.metadata or {}).get("chunk_id", 0)), d.page_content or ""))
    if not items: return ""
    items.sort(key=lambda x: x[0])

    seen = set()
    merged_lines = []
    for _, txt in items:
        for line in (txt.splitlines()):
            norm = _vn_norm(line)
            if norm and norm in seen:
                continue
            seen.add(norm)
            merged_lines.append(line)
    text = "\n".join(merged_lines).strip()

    if len(text) > max_chars:
        cut = text[:max_chars]
        i = cut.rfind("\n")
        text = cut if i < 200 else cut[:i]
    return text

def _parse_jd_header(text: str) -> dict:
    fields = {"position": None, "dept": None, "code": None}
    for line in text.splitlines():
        raw = line.strip()
        if not raw: continue
        vn = _vn_norm(raw)
        if fields["position"] is None and vn.startswith("vi tri"):
            fields["position"] = raw.split(":", 1)[-1].strip(" -:\t"); continue
        if fields["dept"] is None and vn.startswith("bo phan"):
            fields["dept"] = raw.split(":", 1)[-1].strip(" -:\t"); continue
        if fields["code"] is None and (vn.startswith("so ho so") or "txm jd" in vn or "txm.jd" in vn):
            m = re.search(r"(TXM\.\s*JD[.\- ]*\d+)", raw, re.IGNORECASE)
            fields["code"] = (m.group(1).replace(" ", "") if m else raw.split(":",1)[-1].strip())
            continue
    return fields

def _cleanup_jd_text(raw: str) -> str:
    if not raw: return raw
    # 1) bỏ header công ty lặp
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        vn = _vn_norm(s)
        if ("cong ty co phan tiximax" in vn) or ("ban mo ta cong viec" in vn):
            continue
        if vn.startswith("vi tri") or vn.startswith("bo phan") or vn.startswith("so ho so"):
            continue
        lines.append(s)
    t = "\n".join(lines)

    # 2) tách heading A./B./C. khỏi nội dung nếu dính
    t = re.sub(r"(?m)^([A-E]\.\s*[^\n]{1,80}?)(\s{2,}|\s)(?=[A-Za-zÀ-ỹ0-9])", r"\1\n", t)

    # 3) chuẩn hóa khoảng trắng, khử trùng lặp theo đoạn
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    paras, seen = [], set()
    for para in re.split(r"\n{2,}", t):
        p = para.strip()
        if not p: continue
        key = _vn_norm(p)
        if key in seen: continue
        seen.add(key); paras.append(p)
    t = "\n\n".join(paras)

    # 4) gộp block thời gian/địa điểm nếu lặp
    t = re.sub(r"(?is)(Thời gian làm việc:[\s\S]*?Địa điểm làm việc:[^\n]*)(?:\n+\s*\1)+", r"\1", t)

    # 5) header gọn
    hdr = []
    fields = _parse_jd_header(raw)
    if fields.get("position"): hdr.append(f"Vị trí: {fields['position']}")
    if fields.get("dept"):     hdr.append(f"Bộ phận: {fields['dept']}")
    if fields.get("code"):     hdr.append(f"Số hồ sơ: {fields['code']}")
    t = (("\n".join(hdr) + "\n\n") if hdr else "") + t
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t

def _cleanup_sop_text(raw: str) -> str:
    if not raw: return raw
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            lines.append(""); continue
        vn = _vn_norm(s)
        if ("cong ty co phan tiximax" in vn) or ("tai lieu dao tao" in vn) or ("so ho so" in vn):
            continue
        lines.append(s)
    t = "\n".join(lines)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"(?m)^((?:Bước|Buoc)\s*\d+\s*[:\-]|[IVXLC]+\.\s+|\d+\.\s+)(?=\S)", r"\1\n", t, flags=re.IGNORECASE)

    paras, seen = [], set()
    for para in re.split(r"\n{2,}", t):
        p = para.strip()
        if not p: continue
        key = _vn_norm(p)
        if key in seen: continue
        seen.add(key); paras.append(p)
    t = "\n\n".join(paras).strip()
    return t

def _format_fullcopy_output(title: str, header: str, raw: str, fence="text") -> str:
    parts = []
    if title:  parts.append(f"**{title}**")
    if header: parts.append(header)
    if raw:    parts.append(f"```{fence}\n{raw}\n```")
    return "\n\n".join(parts).strip()

# ----------------------------- #
#            LLM I/O            #
# ----------------------------- #

def _init_gemini():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY / GOOGLE_API_KEY")
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    return genai

def ask_gemini(genai, model_name: str, sys_prompt: str, user_prompt: str):
    model = genai.GenerativeModel(model_name, system_instruction=sys_prompt)
    resp = model.generate_content(user_prompt)
    return (resp.text or "").strip()

def _qr_llm_aliases(question: str) -> List[str]:
    if not USE_QR_LLM_HR: return []
    try:
        genai = _init_gemini()
        model = genai.GenerativeModel(QR_LLM_MODEL_HR)
        prompt = f"""Sinh tối đa {QR_NUM_ALIASES_HR} alias ngắn (<=5 từ) cho câu sau (Việt/Anh).
CÂU: "{question}"
Chỉ in danh sách, mỗi dòng 1 alias."""
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
        out, seen = [], set()
        for line in text.splitlines():
            a = line.strip("-*• \t").strip()
            if not a: continue
            n = _norm(a)
            if n not in seen:
                out.append(a); seen.add(n)
        if out: print(f"[QR-LLM] aliases={out}")
        return out[:QR_NUM_ALIASES_HR]
    except Exception as e:
        print(f"[WARN] QR-LLM lỗi: {e}")
        return []

def _prf_phrases(vs, question: str) -> List[str]:
    if not USE_PRF_HR: return []
    docs = vs.similarity_search(f"query: {_norm(question)}", k=PRF_K_SEM_HR)
    txt = " ".join(d.page_content for d in docs)
    tokens = re.findall(r"[a-zA-Z0-9À-ỹ\.]+", _norm(txt))
    bag: Dict[str,int] = {}
    for n in PRF_NGRAMS_HR:
        for i in range(0, max(0, len(tokens)-n+1)):
            g = " ".join(tokens[i:i+n]).strip()
            if len(g) >= PRF_MIN_LEN_CHARS_HR:
                bag[g] = bag.get(g, 0) + 1
    cand = sorted(bag.items(), key=lambda x: x[1], reverse=True)
    out = [w for w,_ in cand[:PRF_TOP_PHRASES_HR]]
    if out: print(f"[PRF] phrases={out}")
    return out

def _mini_llm_decorate(raw_text: str, task: str) -> str:
    if not raw_text or not MINI_LLM_ON_FULLCOPY_HR: return ""
    try:
        genai = _init_gemini()
        model = genai.GenerativeModel(GEMINI_MODEL_ANSWER_HR)
        if task == "ascii_tree":
            instr = (
                "Tạo sơ đồ ASCII có đánh số phân cấp (├─, └─, │) từ đoạn sau.\n"
                "Không thêm giải thích/nguồn. Tối đa ~" + str(MINI_LLM_MAXTOK_HR) + " từ.\n"
                "<<<\n" + raw_text[:4000] + "\n>>>"
            )
        elif task == "prefix_summary":
            instr = (
                "Tóm tắt 3–6 bullet siêu ngắn, không nguồn/citation, tối đa " + str(MINI_LLM_MAXTOK_HR) + " từ.\n"
                "<<<\n" + raw_text[:3000] + "\n>>>"
            )
        else:
            instr = (
                "Viết 3–5 bullet checklist áp dụng, ngắn gọn, không nguồn/citation, tối đa "
                + str(MINI_LLM_MAXTOK_HR) + " từ.\n"
                "<<<\n" + raw_text[:3000] + "\n>>>"
            )
        resp = model.generate_content(instr)
        header = (resp.text or "").strip()
        return strip_citations(header) if STRIP_CITATIONS_HR else header
    except Exception as e:
        print(f"[WARN] mini-LLM lỗi: {e}")
        return ""

# ----------------------------- #
#            MAIN API           #
# ----------------------------- #

def answer_with_rag(question: str) -> Tuple[str, List[Dict[str, Any]]]:
    vs = load_vs()
    intent = classify_intent(question)  # "ORG" | "JD" | "FORM" | "OTHER"

    # --- Query Expansion ---
    aliases = _qr_llm_aliases(question)
    phrases = _prf_phrases(vs, question)

    if intent == "ORG":
        extra_alias = ["sơ đồ tổ chức nhân viên", "sơ đồ tổ chức", "cơ cấu tổ chức",
                       "organizational chart", "org chart", "sơ đồ công ty"]
        seen = {_norm(a) for a in aliases}
        for a in extra_alias:
            if _norm(a) not in seen:
                aliases.append(a); seen.add(_norm(a))
        phrases = (phrases or []) + ["1.1", "1.2", "1.3.1", "1 3 1"]
        phrase_boost = max(2, PHRASE_BOOST_TIMES_HR * 2)
    else:
        phrase_boost = PHRASE_BOOST_TIMES_HR

    boosted = []
    for p in (phrases or []):
        boosted += [p] * max(1, phrase_boost)
    phrases = boosted

    # --- Lex query ---
    lexinfo = build_lex_query(question, aliases=aliases, phrases=phrases)
    if os.environ.get("DEBUG_QE_HR","1").lower() not in ("0","false"):
        print(f"[Expanded] {lexinfo['lex_query']}")

    # --- Retrieve & Rerank ---
    docs = hybrid_retrieve(vs, question, lex_query=lexinfo["lex_query"])
    try:
        ranked = rerank(question, docs)
    except Exception as e:
        print(f"[WARN] rerank failed: {e}")
        ranked = [(d, None) for d in docs]

    if not ranked:
        answer = "Không tìm thấy nội dung phù hợp trong tài liệu."
        _LAST.update(question=question, answer=answer, trace=[])
        return answer, []

    # ---------------- ORG FULLCOPY ----------------
    if ORG_FULLCOPY_HR and is_org_request(question):
        src = ORG_SOURCE_HINT_HR or pick_org_source(ranked)
        raw = read_full_source_text(src) if src else None
        if not raw:
            raw = "\n".join(d.page_content for d, _ in ranked if (d.metadata or {}).get("source")==src).strip() if src else ""
        if not raw:
            answer = "Không tìm thấy tài liệu sơ đồ tổ chức."
            trace = _make_trace(ranked)
            _LAST.update(question=question, answer=answer, trace=trace)
            return answer, trace

        raw = _normalize_raw(raw)
        header = _mini_llm_decorate(raw, MINI_LLM_TASK_ORG_HR)
        answer = _format_fullcopy_output("Sơ đồ tổ chức nhân viên", header, raw, fence="text")
        if STRIP_CITATIONS_HR: answer = strip_citations(answer)
        answer = cleanup_org_answer(answer)
        trace = _make_trace(ranked)
        _LAST.update(question=question, answer=answer, trace=trace)
        return answer, trace

    # ---------------- SOP FULLCOPY ----------------
    SOP_FULLCOPY = os.environ.get("SOP_FULLCOPY_HR", "0").strip().lower() not in ("0", "false")
    if SOP_FULLCOPY and is_sop_request(question):
        src = pick_sop_source(ranked)
        raw = read_full_source_text(src) if src else None
        if not raw:
            raw = "\n".join(d.page_content for d, _ in ranked if (d.metadata or {}).get("source")==src).strip() if src else ""
        answer = _cleanup_sop_text(raw or "")
        if STRIP_CITATIONS_HR: answer = strip_citations(answer)
        answer = _format_fullcopy_output("Quy trình/SOP", "", answer, fence="text")
        trace = _make_trace(ranked)
        _LAST.update(question=question, answer=answer, trace=trace)
        return answer, trace

    # ---------------- JD BRANCH ----------------
    if is_jd_request(question):
        ranked = _jd_reweight(question, ranked)
        best_src = (ranked[0][0].metadata or {}).get("source") if ranked else None

        if JD_FULLCOPY_HR:
            raw = read_full_source_text(best_src) if best_src else None
            if not raw:
                raw = _merge_chunks_same_source(ranked, best_src, MAX_CHARS_CTX_HR * 3)
            clean = _cleanup_jd_text(strip_citations(raw or "") if STRIP_CITATIONS_HR else (raw or ""))
            answer = _format_fullcopy_output("Mô tả công việc", "", clean, fence="text")
            trace = _make_trace(ranked[:10])
            _LAST.update(question=question, answer=answer, trace=trace)
            return answer, trace

        # Không fullcopy: dùng LLM nhưng chỉ với context từ 1 source tốt nhất
        merged = _merge_chunks_same_source(ranked, best_src, MAX_CHARS_CTX_HR)
        ctx = f"[{best_src}|*]\n{merged}" if merged else build_context(ranked, MAX_CHARS_CTX_HR)

        genai = _init_gemini()
        sys_prompt = get_system_prompt(PROFILE_HR)
        user_prompt = (
            "Trả lời đúng theo JD trong ngữ cảnh. Không bịa. "
            "Không trộn tài liệu khác. Trả về nội dung sạch, mạch lạc.\n\n"
            f"Ngữ cảnh:\n{ctx}\n\nCâu hỏi: {question}"
        )
        t0 = time.time()
        answer_raw = ask_gemini(genai, GEMINI_MODEL_ANSWER_HR, sys_prompt, user_prompt)
        t1 = time.time()
        if METRICS_HR: print(f"[METRIC] t_llm={t1-t0:.3f}s")
        ans = strip_citations(answer_raw) if STRIP_CITATIONS_HR else answer_raw
        ans = _cleanup_jd_text(ans)
        trace = _make_trace(ranked[:10])
        _LAST.update(question=question, answer=ans, trace=trace)
        return ans, trace

    # ---------------- FORM FULLCOPY (nếu bật ở intent_router) ----------------
    if intent in ("ORG","JD","FORM") and (FORM_FULLCOPY_HR if intent=="FORM" else False):
        # chọn nguồn theo điểm file (hoặc registry)
        by_file: Dict[str, float] = {}
        for d, s in ranked:
            path = (d.metadata or {}).get("source")
            if not path: continue
            by_file[path] = by_file.get(path, 0.0) + float(s or 0.0)
        scored_sources = sorted(by_file.items(), key=lambda x: x[1], reverse=True)
        doc_type = "form"
        src = pick_best_from_scored(doc_type, scored_sources) or (scored_sources[0][0] if scored_sources else None)

        if not src:
            answer = "Không tìm thấy tài liệu phù hợp."
            trace = _make_trace(ranked)
            _LAST.update(question=question, answer=answer, trace=trace)
            return answer, trace

        if STRICT_SOURCE_MATCH_HR and SOURCE_REGISTRY_PATH:
            rec = get_by_path(src)
            if rec and not verify_hash_if_present(rec):
                print(f"[WARN] Hash mismatch for {src} (registry). Vẫn tiếp tục đọc…")

        raw = read_full_source_text(src) or "\n".join(
            d.page_content for d, _ in ranked if (d.metadata or {}).get("source")==src
        ).strip()
        raw = _normalize_raw(raw)
        header = _mini_llm_decorate(raw, MINI_LLM_TASK_HR)
        answer = _format_fullcopy_output("Mẫu biểu mẫu", header, raw, fence="text")
        if STRIP_CITATIONS_HR: answer = strip_citations(answer)
        trace = _make_trace(ranked)
        _LAST.update(question=question, answer=answer, trace=trace)
        return answer, trace

    # ---------------- GENERAL LLM COMPOSE ----------------
    ctx = build_context(ranked, max_chars=MAX_CHARS_CTX_HR)
    trace = _make_trace(ranked)
    genai = _init_gemini()
    sys_prompt = get_system_prompt(PROFILE_HR)
    user_prompt = f"""
Câu hỏi: {question}

Ngữ cảnh (mỗi đoạn có thẻ [source|chunk_id]):
{ctx}

Yêu cầu:
1) Trả lời tiếng Việt, chỉ dựa trên NGỮ CẢNH.
2) Gắn [source|chunk_id] ngay sau ý tương ứng.
3) Nếu thiếu, nói rõ "không tìm thấy trong tài liệu".
""".strip()
    t0 = time.time()
    answer_raw = ask_gemini(genai, GEMINI_MODEL_ANSWER_HR, sys_prompt, user_prompt)
    t1 = time.time()
    if METRICS_HR: print(f"[METRIC] t_llm={t1-t0:.3f}s")
    answer = strip_citations(answer_raw) if STRIP_CITATIONS_HR else answer_raw
    if is_org_request(question) or re.search(r"[├└│]", answer) or re.search(r"\b\d+(?:\.\d+){1,3}\b", answer):
        answer = cleanup_org_answer(answer)

    _LAST.update(question=question, answer=answer, trace=trace)
    return answer, trace

__all__ = ["answer_with_rag"]
