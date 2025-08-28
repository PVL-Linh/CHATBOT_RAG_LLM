# Processing_Data/Data_processing.py
import re
import unicodedata
from typing import List

# ===== Regex =====
HR_RULE = re.compile(r"^[-=_\u2500\u2014\s]{3,}$")  # ----- ===== ────
PAGE_MARK = re.compile(r"^(?:page|trang)\s*\d{1,3}(?:\s*/\s*\d{1,3})?$", re.IGNORECASE)
HEADER_TAIL = re.compile(r"(giáo trình|tài liệu|chương|phần|section|chapter|page|trang).{0,40}\b\d{1,3}\b$",
                         re.IGNORECASE)
BULLET = re.compile(r"""^(
    [\-\+\*\u2022\u2023\u25E6\u2219\u00B7\u2043]\s+ |   # • - + *
    \d{1,3}[\.\)]\s+                                    # 1. / 1)
)$""", re.VERBOSE)
TABLE_LIKE = re.compile(r"\s{2,}|\t|\s\|\s")            # nhiều space/tab/pipe
MATH_EXPR = re.compile(r"(?=.*\d)(?=.*[\+\-\*/=<>])[A-Za-z0-9\s\+\-\*/=<>\(\)\[\]\.,:^_\\%]+$")

def _normalize_spaces(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _should_drop_header_footer(line: str, idx: int, total: int) -> bool:
    """Chỉ loại header/footer ở rìa trang (±3 dòng). KHÔNG xoá số 0 nội dung."""
    s = (line or "").strip()
    if not s:
        return False
    if HR_RULE.fullmatch(s):
        return True
    if (PAGE_MARK.match(s) or HEADER_TAIL.search(s)) and (idx < 3 or idx > total - 4):
        return True
    if s.isdigit() and (idx < 3 or idx > total - 4):
        try:
            n = int(s)
            if 1 <= n <= 500:
                return True
        except Exception:
            pass
    return False

def looks_like_table_cell(s: str) -> bool:
    """Heuristic nhận diện ô bảng ngay cả khi không có nhiều khoảng trắng."""
    s = (s or "").strip().lower()
    if not s:
        return False
    if any(k in s for k in ["tr/sản phẩm", "cái", "vnd", "đ", "phụ thu", "chi tiết"]):
        return True
    if "<" in s or ">" in s or "/" in s:
        return True
    if re.search(r"(\b0\b|\d{1,3}(?:[.,]\d{3})+|\d+[.,]\d+)", s):
        return True
    return False

def _latexify(line: str) -> str:
    """LaTeX hoá thận trọng: chỉ với biểu thức thật sự, KHÔNG áp cho các dòng bảng."""
    raw = (line or "").strip()
    if 2 <= len(raw) <= 240 and MATH_EXPR.match(raw) and not re.search(r"[.!?]$", raw):
        op = len(re.findall(r"[\+\-\*/=<>]", raw))
        alpha = len(re.findall(r"[A-Za-z]", raw))
        if op >= 2 or (op >= 1 and alpha <= 10):
            return f"$$ {raw} $$"
    return raw

def _flush_table_seq(table_buffer: List[str], result: List[str], mode: str = "flatten"):
    """Gộp các dòng bảng thành hàng: category | detail | fee (nếu nhận diện được)."""
    if not table_buffer:
        return
    if mode == "keep":
        result.extend(table_buffer)
        table_buffer.clear()
        return

    category = None
    pending_detail = None
    for ln in table_buffer:
        low = ln.lower()
        has_num = bool(re.search(r"\d", low))
        is_fee = bool(re.search(r"(\b0\b|\d{1,3}(?:[.,]\d{3})+|vnd|đ|/cái|/thùng)", low))
        is_detail = ("tr/sản phẩm" in low) or ("chi tiết" in low) or ("<" in low) or (">" in low)

        if not has_num and not is_detail and not is_fee:
            category = ln
            continue

        if is_detail and not pending_detail:
            pending_detail = ln
            continue

        if (is_fee or has_num) and pending_detail:
            cat = category or ""
            row = f"{cat} | {pending_detail} | {ln}"
            result.append(row)
            pending_detail = None
            continue

        # fallback: không match heuristic thì giữ nguyên
        result.append(ln)

    table_buffer.clear()

# ===== Main cleaner =====
def clean_page_text(
    text: str,
    *,
    drop_headers: bool = True,
    keep_tables: bool = True,
    table_mode: str = "flatten",   # "keep" | "flatten" | "drop"
    latex_math: bool = True,
) -> str:
    """
    - drop_headers: bỏ header/footer/số trang ở rìa.
    - keep_tables + table_mode: xử lý bảng (giữ, gộp, bỏ).
    - latex_math: LaTeX hoá biểu thức (không áp cho dòng bảng).
    """
    text = unicodedata.normalize("NFKC", text or "")
    lines = text.splitlines()
    total = len(lines)

    filtered: List[str] = []
    for i, ln in enumerate(lines):
        if drop_headers and _should_drop_header_footer(ln, i, total):
            continue
        filtered.append((ln or "").rstrip())

    result: List[str] = []
    paragraph = ""
    table_buffer: List[str] = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph.strip():
            result.append(paragraph.strip())
        paragraph = ""

    def flush_table():
        nonlocal table_buffer
        if not table_buffer:
            return
        if table_mode == "flatten":
            _flush_table_seq(table_buffer, result, mode="flatten")
        elif table_mode == "keep":
            result.extend(table_buffer)
            table_buffer.clear()
        else:  # drop
            table_buffer.clear()

    for ln in filtered:
        ln = _normalize_spaces(ln)

        if not ln:
            flush_table()
            flush_paragraph()
            continue

        # Bảng? (ưu tiên nhận diện bảng trước; không LaTeX hóa dòng bảng)
        if keep_tables and (TABLE_LIKE.search(ln) or looks_like_table_cell(ln)):
            flush_paragraph()
            table_buffer.append(ln)
            continue
        else:
            flush_table()

        # Bullet?
        if BULLET.match(ln):
            flush_paragraph()
            result.append(ln)
            continue

        # LaTeX?
        if latex_math:
            latex_ln = _latexify(ln)
            if latex_ln.startswith("$$") and latex_ln.endswith("$$"):
                flush_paragraph()
                result.append(latex_ln)
                continue
            ln = latex_ln

        # Ghép câu
        if re.search(r"[.!?]$", ln):
            paragraph += ln + " "
            flush_paragraph()
        elif re.search(r":$", ln):
            flush_paragraph()
            result.append(ln)
        else:
            paragraph += ln + " "

    flush_table()
    flush_paragraph()
    return "\n\n".join(result)
