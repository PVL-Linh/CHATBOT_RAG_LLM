"""
engine_hr.py — HR RAG (Tiximax)

Bản đã vá lỗi:
- Chặn QR-LLM lệch nghĩa khi hỏi JD (tránh "Just Do It").
- Ưu tiên đúng file JD + ghép chunk không lặp, dọn header/footer.
- Sửa logic vẽ nhánh: bỏ điều kiện luôn-đúng, xóa code unreachable.
- Thêm fallback import cho Document (nếu langchain_core không có).

Public API:
- answer_with_rag(question: str) -> (answer, trace)
- continue_with_last_accountant(followup: str) -> (answer, trace)
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Set
try:
    from langchain_core.documents import Document
except Exception:
    from typing import Any as _Any
    Document = _Any

from app.config.config_accountant import (
    MAX_CHARS_CTX_ACCOUNTANT, PROFILE_ACCOUNTANT, STRIP_CITATIONS_ACCOUNTANT, DEBUG_QE_ACCOUNTANT, METRICS_ACCOUNTANT, 
    USE_QR_LLM_ACCOUNTANT, QR_LLM_MODEL_ACCOUNTANT, QR_NUM_ALIASES_ACCOUNTANT,
    USE_PRF_ACCOUNTANT, PRF_K_SEM_ACCOUNTANT, PRF_NGRAMS_ACCOUNTANT, PRF_TOP_PHRASES_ACCOUNTANT, PRF_MIN_LEN_CHARS_ACCOUNTANT,
    PHRASE_BOOST_TIMES_ACCOUNTANT,
    ORG_FULLCOPY_ACCOUNTANT, JD_FULLCOPY_ACCOUNTANT,
    ORG_SOURCE_HINT_ACCOUNTANT,
)
from app.config.paths import DATA_DIR_ACCOUNTANT, GEMINI_MODEL_ANSWER_ACCOUNTANT, GEMINI_MODEL_JUDGE_ACCOUNTANT
from .prompts_accountant import get_system_prompt
from app.rag_hr.postprocess import strip_citations, cleanup_org_answer
from app.rag_accountant.hybrid_accountant import load_vs, hybrid_retrieve, build_lex_query_accountant
from app.rag_hr.rerank_hr import rerank
from app.rag_hr.intent_router_hr import classify_intent
from app.rag_hr.gemini_client_hr import init_gemini, ask_gemini
from app.rag_hr.judge_hr import judge_answer
from app.rag_hr.context_hr import build_context as _build_context

__all__ = ["answer_with_rag_accountant", "continue_with_last_accountant"]

# =====================================================================
#  State
# =====================================================================
_LAST: Dict[str, Any] = {
    "question": "",
    "answer": "",
    "trace": [],
    "intent": "",
    "source": "",
}

# === Passthrough flags ===
STRICT_ORG_PASSTHRU = (os.environ.get("STRICT_ORG_PASSTHRU","1").lower() not in ("0","false","no"))
STRICT_JD_PASSTHRU  = (os.environ.get("STRICT_JD_PASSTHRU","1").lower() not in ("0","false","no"))
STRICT_FORM_PASSTHRU= (os.environ.get("STRICT_FORM_PASSTHRU","1").lower() not in ("0","false","no"))
WRAP_TREE_AS_CODE   = (os.environ.get("WRAP_TREE_AS_CODE","1").lower() not in ("0","false","no"))

# =====================================================================
#  Follow-up patterns
# =====================================================================
FOLLOWUP_REDRAW_PAT = re.compile(r"\b(v[eê]̃?\s*l[ạ]i|ve lai|draw|redraw|nh[á]nh|branch|ve|vẽ)\b", re.I)
FOLLOWUP_CONT_PAT   = re.compile(r"\b(ti[ế]p|ti[ế]p tục|tiếp tục|show\s*again|continue|hi[ẹ]n thị lại)\b", re.I)
FOLLOWUP_REVIEW_PAT = re.compile(r"\b(nh[ậ]n x[é]t|d[á]nh gi[á]|review|g[ó]p [ýy]|t[ôo]́i [u]u|cải ti[êe]́n|đề xuất|de xuat)\b", re.I)

# =====================================================================
#  Dept synonyms -> filename hints
# =====================================================================

def _strip_accents(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

# Khóa logic cho từng sơ đồ chuyên biệt
# --- THAY TOÀN BỘ KHỐI NÀY ---
DEPT_SYNONYMS: Dict[str, List[str]] = {
    "ke_toan": [
        "kế toán", "ke toan", "ketoan",
        "tài chính", "tai chinh",
        "accounting", "accountant", "finance", "fin"
    ],
}


def _dept_key_from_text(s: str) -> Optional[str]:
    s0 = _strip_accents((s or "").lower())
    s0 = re.sub(r"\s+", " ", s0)
    # Ưu tiên indo trước nếu xuất hiện
    if any(k in s0 for k in DEPT_SYNONYMS["kinh_doanh_indonesia"]):
        return "kinh_doanh_indonesia"
    for k, arr in DEPT_SYNONYMS.items():
        if k == "kinh_doanh_indonesia":
            continue
        for a in arr:
            if f" {a} " in f" {s0} ":
                return k
    return None

def _filename_hints_for_dept(key: Optional[str]) -> List[str]:
    if not key:
        return []
    if key == "ke_toan":
        # các biến thể tên file/thư mục bạn đang dùng
        return ["ke_toan", "accountant", "accounting", "tai_chinh", "finance"]
    return []

# =====================================================================
#  File / source helpers
# =====================================================================

def _read_full_source_text(source_rel: str) -> Optional[str]:
    if not source_rel:
        return None
    candidates = [os.path.join(DATA_DIR_ACCOUNTANT, source_rel)]
    base = os.path.basename(source_rel)
    for root, _, files in os.walk(DATA_DIR_ACCOUNTANT):
        for fn in files:
            if fn == base:
                candidates.append(os.path.join(root, fn))
    seen: Set[str] = set()
    for full in candidates:
        full = os.path.abspath(full)
        if full in seen:
            continue
        seen.add(full)
        if os.path.isfile(full):
            try:
                return open(full, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                pass
    return None


def _pick_best_source_from_trace(trace: List[Dict[str, Any]]) -> Optional[str]:
    if not trace:
        return None
    c = Counter()
    for item in trace:
        src = (item or {}).get("source") or ""
        if src:
            c[src] += 1
    return c.most_common(1)[0][0] if c else None


def _prefer_diagram_source(ranked: List[Tuple[Document, Optional[float]]], dept_key: Optional[str]) -> Optional[str]:
    """Ưu tiên chọn đúng file TREE theo bộ phận (nếu có)."""
    hints = _filename_hints_for_dept(dept_key)

    # Nếu là sơ đồ tổng và có hint cấu hình → dùng ngay
    if not dept_key and ORG_SOURCE_HINT_ACCOUNTANT:
        return ORG_SOURCE_HINT_ACCOUNTANT

    def looks_tree(src: str) -> bool:
        s = (src or "").lower()
        return ("tree" in s) or s.endswith("_tree.txt")

    # 1) file tree khớp dept hints
    for d, _ in ranked:
        src = (d.metadata or {}).get("source", "")
        s = (src or "").lower()
        if dept_key and looks_tree(s) and any(h in s for h in hints):
            return src

    # 2) bất kỳ file tree nào
    for d, _ in ranked:
        src = (d.metadata or {}).get("source", "")
        if looks_tree(src):
            return src

    # 3) fallback: top-1 source
    return (ranked[0][0].metadata or {}).get("source")

# =====================================================================
#  QE / Retrieval helpers
# =====================================================================

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _qr_llm_aliases(question: str) -> List[str]:
    if not USE_QR_LLM_ACCOUNTANT:
        return []
    out: List[str] = []
    try:
        genai = init_gemini()
        model = genai.GenerativeModel(QR_LLM_MODEL_ACCOUNTANT)
        prompt = f"""Sinh tối đa {QR_NUM_ALIASES_ACCOUNTANT} alias ngắn  cho câu sau, tiếng Việt/Anh.
            CÂU: "{question}"
            Chỉ in danh sách, mỗi dòng 1 alias."""
        resp = model.generate_content(prompt)
        print("[QR-LLM] response received{resp}")
        text = (resp.text or "").strip()
        seen = set()
        for line in text.splitlines():
            a = line.strip("-*• \t").strip()
            if not a:
                continue
            n = _norm(a)
            if n not in seen:
                out.append(a)
                seen.add(n)
        if DEBUG_QE_ACCOUNTANT and out:
            print(f"[QR-LLM] aliases={out}")
    except Exception as e:
        print(f"[WARN] QR-LLM lỗi: {e}")
    return out[:QR_NUM_ALIASES_ACCOUNTANT]


def _prf_phrases(vs, question: str) -> List[str]:
    if not USE_PRF_ACCOUNTANT:
        return []
    docs = vs.similarity_search(f"query: {_norm(question)}", k=PRF_K_SEM_ACCOUNTANT)
    txt = " ".join(d.page_content for d in docs)
    tokens = re.findall(r"[a-zA-Z0-9À-ỹ\.]+", _norm(txt))
    bag: Dict[str, int] = {}
    for n in PRF_NGRAMS_ACCOUNTANT:
        for i in range(0, max(0, len(tokens) - n + 1)):
            g = " ".join(tokens[i:i + n]).strip()
            if len(g) >= PRF_MIN_LEN_CHARS_ACCOUNTANT:
                bag[g] = bag.get(g, 0) + 1
    cand = sorted(bag.items(), key=lambda x: x[1], reverse=True)
    out = [w for w, _ in cand[:PRF_TOP_PHRASES_ACCOUNTANT]]
    if DEBUG_QE_ACCOUNTANT and out:
        print(f"[PRF] phrases={out}")
    return out

# =====================================================================
#  JD helpers — curated expansion + source picking + dedup join
# =====================================================================

def _is_jd_query(q: str) -> bool:
    n = _norm(q)
    return bool(re.search(r"\b(jd|mô tả công việc|mtcv|job description)\b", n))


def _curated_jd_aliases_and_phrases(q: str) -> Tuple[List[str], List[str]]:
    aliases = ["job description", "mô tả công việc", "mtcv", "JD", "TXM.JD"]
    n = _norm(q)
    if "it" in n:
        aliases += ["IT"]
    if "crm" in n:
        aliases += ["CRM", "CRM Application Engineer"]
    phrases = [
        "Vị trí", "Bộ phận", "Số hồ sơ",
        "Mục tiêu công việc", "Quan hệ công việc",
        "Thời gian và Địa điểm làm việc",
        "Yêu cầu về trình độ và kỹ năng",
        "Trách nhiệm chính", "Quyền Lợi",
        "TXM.JD", "MTCV"
    ]
    return aliases, phrases


def _join_unique_chunks(ranked, source: str) -> str:
    """Ghép các chunk cùng source theo thứ tự, khử đoạn lặp."""
    items: List[Tuple[int, str]] = []
    for d, _ in ranked:
        m = d.metadata or {}
        if m.get("source") == source:
            cid = m.get("chunk_id", -1)
            items.append((cid if isinstance(cid, int) else 10**9, d.page_content or ""))
    items.sort(key=lambda x: x[0])
    seen: Set[str] = set()
    out_parts: List[str] = []
    for _, txt in items:
        for para in re.split(r"\n{2,}", (txt or "").strip()):
            key = re.sub(r"\s+", " ", para).strip().lower()
            if key and key not in seen:
                seen.add(key)
                out_parts.append(para.strip())
    return "\n\n".join(out_parts).strip()


def _clean_jd_headers(raw: str) -> str:
    """Loại header/footer JD lặp + rút gọn dòng trống."""
    if not raw:
        return raw
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.splitlines()]
    cleaned: List[str] = []
    seen_line: Set[str] = set()
    ban = {
        "công ty cổ phần tiximax bản mô tả công việc",
        "cong ty co phan tiximax ban mo ta cong viec",
    }
    for ln in lines:
        if not ln:
            cleaned.append("")
            continue
        key = ln.lower()
        if key in ban:
            if key in seen_line:
                continue
            seen_line.add(key)
        cleaned.append(ln)
    txt = "\n".join(cleaned)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def _pick_best_jd_source(ranked, question: str) -> Optional[str]:
    """Ưu tiên file JD khớp mã (TXM.JD.xx), sau đó JD-IT, rồi JD bất kỳ, cuối cùng top-1."""
    n = _norm(question)
    m = re.search(r"txm\.jd\.(\d+)", n)
    if m:
        code = m.group(0)
        for d, _ in ranked:
            src = (d.metadata or {}).get("source", "").lower()
            if code in src:
                return (d.metadata or {}).get("source")
    for d, _ in ranked:
        s = (d.metadata or {}).get("source", "").lower()
        if "txm.jd" in s and (" it" in s or "it " in s or " it." in s):
            return (d.metadata or {}).get("source")
    for d, _ in ranked:
        s = (d.metadata or {}).get("source", "").lower()
        if "txm.jd" in s or "mtcv" in s:
            return (d.metadata or {}).get("source")
    return (ranked[0][0].metadata or {}).get("source")

# =====================================================================
#  Org subtree extractors
# =====================================================================
_CODE_FENCE = re.compile(r"^```.*?$|^```$", re.MULTILINE)


def _strip_code_fences(s: str) -> str:
    if not s:
        return ""
    return _CODE_FENCE.sub("", s).strip()


def _visual_indent(line: str) -> int:
    m = re.match(r'^[\s│├└─]+', line or '')
    return len(m.group(0)) if m else 0


_NUM_PREFIX_RE = re.compile(r'^\s*[│├└─\s]*((?:\d+(?:\.\d+)*))\s+')


def _number_prefix(line: str) -> Optional[str]:
    m = _NUM_PREFIX_RE.match(line or "")
    return m.group(1) if m else None


def _match_line_title(line: str, title_regex: str) -> bool:
    # Match nguyên bản
    if re.search(title_regex, line, re.I):
        return True
    # Match không dấu
    return bool(re.search(title_regex, _strip_accents(line).lower(), re.I))


def _relax_patterns_for_token(token: str) -> List[str]:
    t = _strip_accents(token or "").lower().strip()
    if not t:
        return []
    pats: List[str] = []
    if re.fullmatch(r"[a-z0-9]+", t):
        pats = [rf"\b{re.escape(t)}\b", re.escape(t)]
    else:
        pats = [re.escape(t)]
    # Chỉ giữ nhóm Kế toán/Tài chính
    if t in ("ke toan", "ketoan", "ke_toan", "kế toán",
             "tai chinh", "tài chính",
             "accounting", "accountant", "finance", "fin"):
        pats += ["ke toan", "ketoan", "accounting", "accountant", "tai chinh", "finance", r"\bfin\b"]
    return list(dict.fromkeys(pats))

def extract_subtree_by_title(ascii_tree: str, title_regex: str = r"marketing") -> str:
    if not ascii_tree:
        return ""
    body = _strip_code_fences(ascii_tree)
    lines = body.splitlines()

    def _find_start(pat: str) -> Tuple[int, Optional[int], Optional[str]]:
        start_idx, base_indent, base_num = -1, None, None
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            if _match_line_title(ln, pat):
                start_idx = i
                base_indent = _visual_indent(ln)
                base_num = _number_prefix(ln)
                break
        return start_idx, base_indent, base_num

    tried = [title_regex]
    start_idx, base_indent, base_num = _find_start(title_regex)
    if start_idx < 0:
        # nới pattern nếu token
        for pat in _relax_patterns_for_token(title_regex):
            if pat in tried:
                continue
            tried.append(pat)
            start_idx, base_indent, base_num = _find_start(pat)
            if start_idx >= 0:
                if DEBUG_QE_ACCOUNTANT:
                    print(f"[ORG-REDRAW] Relaxed matched by: {pat}")
                break
    if start_idx < 0:
        if DEBUG_QE_ACCOUNTANT:
            print(f"[ORG-REDRAW] No match for: {title_regex}. Tried={tried}")
        return ""

    out: List[str] = [lines[start_idx].rstrip()]
    for j in range(start_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        ind = _visual_indent(ln)
        if base_num:
            num = _number_prefix(ln)
            if num and (num == base_num or num.startswith(base_num + ".")):
                out.append(ln.rstrip())
                continue
        if ind > (base_indent or 0):
            out.append(ln.rstrip())
        else:
            break
    return "\n".join(out).strip()

# =====================================================================
#  Follow-up action detection
# =====================================================================

def detect_followup_action(text: str) -> str:
    """Nhận diện follow-up theo từ khóa KHÔNG DẤU (ổn định hơn)."""
    s_raw = (text or "").strip()
    s = _strip_accents(s_raw).lower()

    # REDRAW / VẼ LẠI / VẼ NHÁNH
    redraw_keys = [
        "ve lai", "ve tiep", "ve nhanh",
        "redraw", "draw again", "draw", "branch", "nhanh", "ve", "hien thi lai", "show again"
    ]
    if any(k in s for k in redraw_keys):
        return "REDRAW"

    # REVIEW / NHẬN XÉT / GÓP Ý / ĐÁNH GIÁ
    review_keys = [
        "nhan xet", "review", "comment", "gop y", "danh gia", "nhan dinh",
        "de xuat", "nhan xet phan tren", "nhan xet tren", "nhan xet so do"
    ]
    if any(k in s for k in review_keys):
        return "REVIEW"

    # CONTINUE
    continue_keys = ["tiep tuc", "continue"]
    if any(k in s for k in continue_keys):
        return "CONTINUE"

    return "NONE"


def _extract_branch_key(followup: str) -> Optional[str]:
    s_raw = (followup or "").strip()
    if not s_raw:
        return None
    s_norm = _strip_accents(s_raw).lower()
    s_norm = re.sub(r"\s+", " ", s_norm)

    m = re.search(r"(?:nhanh|branch|phan|bo phan|team)\s+([a-z0-9 \-_.]{2,60})", s_norm)
    if m:
        key = m.group(1).strip(" .-_")
        parts = [p for p in key.split() if p]
        if parts:
            return parts[-1]

    for _, arr in DEPT_SYNONYMS.items():
        for kw in arr:
            if f" {kw} " in f" {s_norm} ":
                return kw
    return None

# =====================================================================
#  PUBLIC: New question
# =====================================================================

def answer_with_rag_accountant(question: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    NEW ASK:
    - Nếu câu mới thực ra là follow-up (vẽ/tiếp tục/nhận xét) và có _LAST → route sang continue_with_last_accountant.
    - Nếu là 'sơ đồ <bộ phận>' → ƯU TIÊN chọn đúng file tree của bộ phận (full copy).
    - Các trường hợp khác → RAG + LLM như cũ.
    """
    # Nếu câu mới là follow-up và có bối cảnh, chuyển sang continue
    if _LAST.get("trace"):
        act = detect_followup_action(question)
        if act in ("REDRAW", "REVIEW", "CONTINUE"):
            if DEBUG_QE_ACCOUNTANT:
                print(f"[ROUTER] New text looks like follow-up: act={act} -> continue_with_last_accountant")
            return continue_with_last_accountant(question)

    vs = load_vs()
    intent = classify_intent(question)

    aliases = _qr_llm_aliases(question)
    phrases = _prf_phrases(vs, question)

    # Nếu là truy vấn JD → dùng curated aliases/phrases (tránh "Just Do It")
    if _is_jd_query(question):
        aliases, jd_phrases = _curated_jd_aliases_and_phrases(question)
        phrases = (phrases or []) + jd_phrases

    # build lex
    if intent == "ORG":
        extra_alias = [
            "sơ đồ tổ chức", "cơ cấu tổ chức", "organizational chart", "org chart",
            "sơ đồ công ty", "sơ đồ nhân sự", "organizational structure", "company structure",
            # Ưu tiên phòng kế toán
            "kế toán", "accounting", "tài chính", "finance"
        ]
        seen = {_norm(a) for a in aliases}
        for a in extra_alias:
            if _norm(a) not in seen:
                aliases.append(a)
                seen.add(_norm(a))
        phrases = (phrases or []) + ["1.1", "1.2", "1.3.1"]
        phrase_boost = max(2, PHRASE_BOOST_TIMES_ACCOUNTANT * 2)
    else:
        phrase_boost = PHRASE_BOOST_TIMES_ACCOUNTANT

    boosted: List[str] = []
    for p in (phrases or []):
        boosted += [p] * max(1, phrase_boost)
    phrases = boosted

    lexinfo = build_lex_query_accountant(question, aliases=aliases, phrases=phrases)
    if DEBUG_QE_ACCOUNTANT:
        print(f"[LEX_QUERY] {lexinfo['lex_query']}")
        print(f"[Expanded] {lexinfo['lex_query']}")

    docs = hybrid_retrieve(vs, question, lex_query=lexinfo["lex_query"])
    try:
        ranked = rerank(question, docs)
    except Exception as e:
        print(f"[WARN] rerank failed: {e}")
        ranked = [(d, None) for d in docs]

    if not ranked:
        answer = "Không tìm thấy nội dung phù hợp trong tài liệu."
        _LAST.update(question=question, answer=answer, trace=[], intent=intent, source="")
        return answer, []

    # ===== ORG: CHỌN FILE TREE ĐÚNG BỘ PHẬN (FULL COPY) =====
    if intent == "ORG" and ORG_FULLCOPY_ACCOUNTANT:
        dept_key = _dept_key_from_text(question)  # vd: "marketing"/"kinh_doanh"/"kinh_doanh_indonesia"/None
        src = _prefer_diagram_source(ranked, dept_key)
        raw = _read_full_source_text(src) if src else None
        if not raw:
            # Fallback: ghép các chunk cùng source
            raw = "".join(d.page_content for d, _ in ranked if (d.metadata or {}).get("source") == src)

        tree_text = (raw or "").strip()
        if STRICT_ORG_PASSTHRU:
            ans = f"```text\n{tree_text}\n```" if WRAP_TREE_AS_CODE else tree_text
        else:
            # chế độ cũ: strip_citations + cleanup (không khuyến nghị)
            ans = strip_citations(tree_text) if STRIP_CITATIONS_ACCOUNTANT else tree_text
            ans = cleanup_org_answer(ans)
        trace = _make_trace(ranked)
        _LAST.update(question=question, answer=ans, trace=trace, intent="ORG", source=(src or ""))
        return ans, trace

    # ===== JD FULL COPY (đã làm sạch & không lặp) =====
    qn_norm = _norm(question)
    is_jd = bool(re.search(r"\b(jd|mô tả công việc|job description|mtcv)\b", qn_norm))
    if JD_FULLCOPY_ACCOUNTANT and is_jd:
        best_src = _pick_best_jd_source(ranked, question)
        raw = _read_full_source_text(best_src) if best_src else None
        if not raw:
            raw = _join_unique_chunks(ranked, best_src or "")
        raw = (raw or "").strip()
        raw = _clean_jd_headers(raw)
        if STRICT_JD_PASSTHRU:
            ans = raw
        else:
            ans = strip_citations(raw) if STRIP_CITATIONS_ACCOUNTANT else raw
        trace = _make_trace(ranked)
        _LAST.update(question=question, answer=ans, trace=trace, intent=intent, source=(best_src or ""))
        return ans, trace

    # ===== LLM compose (OTHER) =====
    ctx = _build_context(ranked, max_chars=MAX_CHARS_CTX_ACCOUNTANT)
    trace = _make_trace(ranked)
    genai = init_gemini()
    sys_prompt = get_system_prompt()
    user_prompt = f"""
        Câu hỏi: {question}

        Ngữ cảnh (mỗi đoạn có thẻ [source|chunk_id]):
        {ctx}

        Yêu cầu:
        1) Trả lời tiếng Việt, chỉ dựa trên NGỮ CẢNH.
         CHÀO HỎI / HỘI THOẠI NGẮN
        - Nếu đầu vào là lời chào ngắn (≤ 6 từ, hoặc khớp các mẫu: hello/hi/hey/chào/xin chào/alo + emoji 👋🙂),
        TRẢ LỜI CHÍNH XÁC 1 CÂU:
        "Xin chào! Tôi là Trợ lý Ảo Kế toán của Tiximax. Tôi có thể hỗ trợ bạn điều gì?"
        """.strip()
    t0 = time.time()
    answer_raw = ask_gemini(genai, GEMINI_MODEL_ANSWER_ACCOUNTANT, sys_prompt, user_prompt)
    t1 = time.time()
    if METRICS_ACCOUNTANT:
        print(f"[METRIC] t_llm={t1 - t0:.3f}s")
    answer = strip_citations(answer_raw) if STRIP_CITATIONS_ACCOUNTANT else answer_raw

    try:
        report = judge_answer(question, answer, trace, GEMINI_MODEL_JUDGE_ACCOUNTANT)
        g = float(report.get("groundedness")) if report and report.get("groundedness") is not None else None
        # if (g is not None) and (g < 0.5):
        #     answer = "không tìm thấy trong tài liệu"
    except Exception as e:
        print(f"[WARN] judge failed: {e}")

    if re.search(r"[├└│]", answer) or re.search(r"\b\d+(?:\.\d+){1,3}\b", answer):
        answer = cleanup_org_answer(answer)

    _LAST.update(question=question, answer=answer, trace=trace, intent=intent, source=(trace[0].get("source") if trace else ""))
    return answer, trace

# =====================================================================
#  PUBLIC: Follow-up
# =====================================================================

def _make_trace(ranked: List[Tuple[Document, Optional[float]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d, s in ranked:
        m = d.metadata or {}
        out.append({
            "source": m.get("source", "?"),
            "chunk_id": m.get("chunk_id", -1),
            "score": float(s) if s is not None else None,
            "text": d.page_content,
        })
    return out


def _compose_followup_review(prev_q: str, prev_ans: str, followup: str) -> str:
    """Dùng LLM để 'nhận xét/đề xuất' dựa trên sơ đồ ở prev_ans + yêu cầu follow-up."""
    genai = init_gemini()
    sys = get_system_prompt(PROFILE_ACCOUNTANT)
    user = f"""
        Bạn là chuyên viên Kế toán. Hãy nhận xét ngắn gọn, hành động được.
        Dưới đây là SƠ ĐỒ hiện tại (ASCII):
        ```text
        {_strip_code_fences(prev_ans)}
        ```
        Yêu cầu follow-up của người dùng:
        - {followup}

        Trả lời:
        - Tiếng Việt, gạch đầu dòng súc tích.
        - Không bịa chức danh mới.
        - Nếu đề xuất thay đổi, nêu lý do ngắn + lợi ích.
        """
    return ask_gemini(genai, GEMINI_MODEL_ANSWER_ACCOUNTANT, sys, user)


def _redraw_from_prev(prev_ans: str, followup: str) -> Optional[str]:
    key = _extract_branch_key(followup or "")
    if not key:
        return None
    for pat in _relax_patterns_for_token(key):
        blk = extract_subtree_by_title(prev_ans, title_regex=pat)
        if blk and blk.strip():
            return (f"```text\n{blk}\n```" if WRAP_TREE_AS_CODE else blk)
    return None


def _redraw_from_source(prev_trace: List[Dict[str, Any]], followup: str, last_source: str) -> Optional[str]:
    key = _extract_branch_key(followup or "")
    if not key:
        return None

    # ưu tiên dùng nguồn lần trước nếu có
    src = last_source or _pick_best_source_from_trace(prev_trace)

    # nếu follow-up có dept rõ ràng → cố chọn file tree đúng dept trong trace
    dept_key = _dept_key_from_text(key)
    if dept_key:
        hints = _filename_hints_for_dept(dept_key)
        for t in prev_trace:
            s = (t.get("source") or "").lower()
            if ("tree" in s) and any(h in s for h in hints):
                src = t.get("source")
                break

    raw = _read_full_source_text(src) if src else None
    if not raw:
        return None
    for pat in _relax_patterns_for_token(key):
        blk = extract_subtree_by_title(raw, title_regex=pat)
        if blk and blk.strip():
            return (f"```text\n{blk}\n```" if WRAP_TREE_AS_CODE else blk)
    return None


def continue_with_last_accountant(followup: str) -> Tuple[str, List[Dict[str, Any]]]:
    prev_q = _LAST.get("question", "") or ""
    prev_ans = _LAST.get("answer", "") or ""
    prev_trace = _LAST.get("trace", []) or []
    prev_intent = _LAST.get("intent", "")
    last_source = _LAST.get("source", "") or ""

    if not prev_trace:
        return ("Không có ngữ cảnh trước đó để 'tiếp tục'. Hãy hỏi: 'Sơ đồ tổ chức' trước.", [])

    act = detect_followup_action(followup)
    if DEBUG_QE_ACCOUNTANT:
        print(f"[FOLLOW-UP] act={act} | text={followup}")

    # 1) REDRAW (vẽ nhánh)
    if act == "REDRAW":
        # cắt ngay trên prev_ans
        if prev_ans:
            ans = _redraw_from_prev(prev_ans, followup)
            if ans:
                _LAST.update(question=f"{prev_q}  (follow-up: {followup})", answer=ans, trace=prev_trace, intent="ORG", source=last_source)
                return ans, prev_trace
        # fallback: đọc từ source
        ans = _redraw_from_source(prev_trace, followup, last_source)
        if ans:
            _LAST.update(question=f"{prev_q}  (follow-up: {followup})", answer=ans, trace=prev_trace, intent="ORG", source=last_source)
            return ans, prev_trace
        return (f"Không tìm thấy nhánh phù hợp để vẽ lại cho yêu cầu: '{followup}'. Hãy thử: 'vẽ nhánh Marketing' hoặc 'vẽ nhánh 1.3'.", prev_trace)

    # 2) REVIEW (nhận xét/đánh giá)
    if act == "REVIEW":
        if not prev_ans:
            return ("Chưa có sơ đồ để nhận xét. Hãy hỏi 'Sơ đồ tổ chức' trước.", prev_trace)
        review = _compose_followup_review(prev_q, prev_ans, followup)
        if STRIP_CITATIONS_ACCOUNTANT:
            review = strip_citations(review)
        _LAST.update(question=f"{prev_q}  (follow-up: {followup})", answer=review, trace=prev_trace, intent=prev_intent, source=last_source)
        return review, prev_trace

    # 3) CONTINUE (hiển thị lại)
    if act == "CONTINUE":
        _LAST.update(question=f"{prev_q}  (follow-up: {followup})", answer=prev_ans, trace=prev_trace, intent=prev_intent, source=last_source)
        return prev_ans, prev_trace

    # 4) Nếu follow-up chứa tên bộ phận quen thuộc → coi như REDRAW nhẹ
    quick_key = _dept_key_from_text(followup)
    if quick_key and prev_ans:
        ans = _redraw_from_prev(prev_ans, followup)
        if ans:
            _LAST.update(question=f"{prev_q}  (follow-up: {followup})", answer=ans, trace=prev_trace, intent="ORG", source=last_source)
            return ans, prev_trace

    # fallback: trả lại sơ đồ cũ
    return (prev_ans or "Không rõ yêu cầu tiếp tục.", prev_trace)
