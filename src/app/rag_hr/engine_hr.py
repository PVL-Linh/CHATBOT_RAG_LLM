import os, time, re
from typing import Tuple, List, Dict, Any
from langchain_core.documents import Document

from .config_hr import (
    MAX_CHARS_CTX_HR, GEMINI_MODEL_ANSWER_HR, PROFILE_HR,
    USE_QR_LLM_HR, QR_LLM_MODEL_HR, QR_NUM_ALIASES_HR,
    USE_PRF_HR, PRF_K_SEM_HR, PRF_NGRAMS_HR, PRF_TOP_PHRASES_HR, PRF_MIN_LEN_CHARS_HR,
    PHRASE_BOOST_TIMES_HR, FORM_FULLCOPY_HR, STRIP_CITATIONS_HR, METRICS_HR, ORG_FULLCOPY_HR
)
from .prompts_hr import get_system_prompt
from .postprocess import strip_citations
from .hybrid_hr import load_vs, hybrid_retrieve, build_lex_query
from .rerank_hr import rerank
from .bm25_hr import prepare_bm25_docs
from .config_hr import DATA_DIR_HR

_LAST: Dict[str, Any] = {"question": "", "answer": "", "trace": []}

# ====== LLM helpers ======
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

# ====== QR-LLM & PRF ======
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

ORG_PATTERNS = [
    r"\bsơ\s*đồ\s*tổ\s*chức\b",
    r"\bsơ\s*đồ\s*nhân\s*sự\b",
    r"\borg(?:anizational)?\s*chart\b",
    r"\bsơ\s*đồ\s*công\s*ty\b",
]
def is_org_request(question: str) -> bool:
    q = _norm(question)
    return any(re.search(p, q) for p in ORG_PATTERNS)

def pick_org_source(ranked_pairs):
    # Ưu tiên file tên chứa "so_do_to_chuc" / "to_chuc_nhan_vien" / "tree"
    for d, _ in ranked_pairs:
        src = (d.metadata or {}).get("source", "") or ""
        sn = _norm(src)
        if any(k in sn for k in ["so_do_to_chuc", "to_chuc_nhan_vien", "to_chuc", "tree", "org_chart"]):
            return src
    # nếu không, xét nội dung có chữ 'sơ đồ tổ chức'
    for d, _ in ranked_pairs:
        if "sơ đồ tổ chức" in _norm(d.page_content) or "organizational chart" in _norm(d.page_content):
            return (d.metadata or {}).get("source")
    return (ranked_pairs[0][0].metadata or {}).get("source") if ranked_pairs else None
def _qr_llm_aliases(question: str) -> List[str]:
    if not USE_QR_LLM_HR:
        return []
    try:
        genai = _init_gemini()
        model = genai.GenerativeModel(QR_LLM_MODEL_HR)
        prompt = f"""Sinh tối đa {QR_NUM_ALIASES_HR} cách diễn đạt/alias ngắn (<=5 từ) cho câu sau, tiếng Việt hoặc Anh:
CÂU: "{question}"
Chỉ in ra danh sách dạng mỗi dòng 1 alias, không giải thích."""
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()
        al = []
        for line in text.splitlines():
            line = line.strip("-*• \t").strip()
            if line:
                al.append(line)
        # lược bớt trùng
        seen, uniq = set(), []
        for a in al:
            n = _norm(a)
            if n and n not in seen:
                uniq.append(a)
                seen.add(n)
        if uniq:
            print(f"[QR-LLM] aliases={uniq}")
        return uniq[:QR_NUM_ALIASES_HR]
    except Exception as e:
        print(f"[WARN] QR-LLM lỗi: {e}")
        return []

def _prf_phrases(vs, question: str) -> List[str]:
    if not USE_PRF_HR:
        return []
    # Lấy vài doc semantic và trích n-gram có ý nghĩa
    docs = vs.similarity_search(f"query: {_norm(question)}", k=PRF_K_SEM_HR)
    txt = " ".join(d.page_content for d in docs)
    tokens = re.findall(r"[a-zA-Z0-9À-ỹ]+", _norm(txt))
    phrases = {}
    for n in PRF_NGRAMS_HR:
        for i in range(0, max(0, len(tokens) - n + 1)):
            gram = " ".join(tokens[i:i+n]).strip()
            if len(gram) >= PRF_MIN_LEN_CHARS_HR:
                phrases[gram] = phrases.get(gram, 0) + 1
    # pick top
    cand = sorted(phrases.items(), key=lambda x: x[1], reverse=True)
    out = [w for w,_ in cand[:PRF_TOP_PHRASES_HR]]
    if out:
        print(f"[PRF] phrases={out}")
    return out

# ====== Context builder ======
def build_context(pairs: List[Tuple[Document, float]], max_chars: int = MAX_CHARS_CTX_HR) -> str:
    blocks, used = [], 0
    for d, score in pairs:
        meta = d.metadata or {}
        tag = f"[{meta.get('source','?')}|{meta.get('chunk_id',-1)}]"
        text = (d.page_content or '').strip()
        piece = (f"{tag}\n{text}\n").strip() + "\n"
        if used + len(piece) > max_chars and blocks:
            break
        blocks.append(piece)
        used += len(piece)
    return "\n---\n".join(blocks)

# ====== “biên bản bàn giao” full-form ======
FORM_PATTERNS = [
    r"\bbiên\s*bản\s*bàn\s*giao\b",
    r"\bmẫu\s*biên\s*bản\s*bàn\s*giao\b",
    r"\bbàn\s*giao\s*tài\s*sản\b",
    r"\bbàn\s*giao\s*công\s*cụ\b",
    r"\bhandover\b",
    r"\bcụ thể\b",
]

def is_form_request(question: str) -> bool:
    q = _norm(question)
    strong = any(k in q for k in ["mẫu", "biên bản", "form", "template", "cụ thể", "cu the", "bàn giao"])
    if not strong:
        return False
    return any(re.search(p, q) for p in FORM_PATTERNS)

def pick_handover_source(ranked_pairs):
    # Ưu tiên theo tên file
    for d, _ in ranked_pairs:
        src = (d.metadata or {}).get("source","") or ""
        sn = _norm(src)
        if any(k in sn for k in ["ban_giao", "ban giao", "bien_ban_ban_giao", "bb_ban_giao"]):
            return src
    # Sau đó xét nội dung
    for d, _ in ranked_pairs:
        if "biên bản bàn giao" in _norm(d.page_content) or "bien ban ban giao" in _norm(d.page_content):
            return (d.metadata or {}).get("source")
    return (ranked_pairs[0][0].metadata or {}).get("source") if ranked_pairs else None

def read_full_source_text(source_rel: str) -> str | None:
    if not source_rel:
        return None
    import os
    full = os.path.join(DATA_DIR_HR, source_rel)
    try:
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

# ====== Public API ======
def answer_with_rag(question: str) -> Tuple[str, List[Dict[str, Any]]]:
    vs = load_vs()

    # QE
    aliases = _qr_llm_aliases(question)
    phrases = _prf_phrases(vs, question)
    # Nhân thêm trọng số phrase (bằng cách lặp lại)
    boosted = []
    for p in (phrases or []):
        boosted += [p] * max(1, PHRASE_BOOST_TIMES_HR)
    if boosted:
        phrases = boosted

    # build lex query
    lexinfo = build_lex_query(question, aliases=aliases, phrases=phrases)
    if os.environ.get("DEBUG_QE_HR","1").lower() not in ("0","false"):
        print(f"[Expanded] {lexinfo['lex_query']}")

    # retrieve
    docs = hybrid_retrieve(vs, question, lex_query=lexinfo["lex_query"])
    ranked = rerank(question, docs)

    # FULL-FORM branch
    if ORG_FULLCOPY_HR and is_org_request(question):
        src = pick_org_source(ranked)
        raw = read_full_source_text(src) if src else None
        if not raw:
            # fallback: ghép tất cả chunk cùng source để giữ số mục
            if src:
                raw = "\n".join(d.page_content for d, _ in ranked
                                if (d.metadata or {}).get("source") == src)
            else:
                raw = "\n".join(d.page_content for d, _ in ranked)
        answer = raw or "Không tìm thấy trong tài liệu."
        if STRIP_CITATIONS_HR:
            answer = strip_citations(answer)
        # build trace như hiện tại
        trace = []
        for d, score in ranked:
            m = d.metadata or {}
            trace.append({
                "source": m.get("source","?"),
                "chunk_id": m.get("chunk_id",-1),
                "score": float(score) if score is not None else None,
                "text": d.page_content,
            })
        _LAST.update(question=question, answer=answer, trace=trace)
        return answer, trace

    # Build context
    ctx = build_context(ranked, max_chars=MAX_CHARS_CTX_HR)
    trace = []
    for d, score in ranked:
        m = d.metadata or {}
        trace.append({"source": m.get("source","?"), "chunk_id": m.get("chunk_id",-1),
                      "score": float(score) if score is not None else None, "text": d.page_content})

    # Ask Gemini
    genai = _init_gemini()
    sys_prompt = get_system_prompt(PROFILE_HR)
    user_prompt = f"""
Câu hỏi: {question}

Ngữ cảnh (mỗi đoạn kèm thẻ [source|chunk_id]):
{ctx}

Yêu cầu:
1) Trả lời bằng tiếng Việt.
2) Chỉ dùng thông tin từ NGỮ CẢNH. Không bịa.
3) Khi dẫn chứng, gắn thẻ [source|chunk_id] ngay sau câu/ý tương ứng.
""".strip()

    t0 = time.time()
    answer_raw = ask_gemini(genai, GEMINI_MODEL_ANSWER_HR, sys_prompt, user_prompt)
    t1 = time.time()
    if METRICS_HR:
        print(f"[METRIC] t_llm={t1-t0:.3f}s")

    answer = strip_citations(answer_raw) if STRIP_CITATIONS_HR else answer_raw
    _LAST.update(question=question, answer=answer, trace=trace)
    return answer, trace

# Expose build_lex_query cho route debug
__all__ = ["answer_with_rag", "build_lex_query"]
