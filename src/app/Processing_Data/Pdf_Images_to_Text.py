import fitz  # PyMuPDF
import os
import re
import unicodedata
from typing import List, Tuple, Optional

# ---------- Helpers ----------

INVISIBLE_CHARS = [
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
    "\u2060",  # WORD JOINER
]
SPACE_LIKES = [
    "\u00a0",  # NO-BREAK SPACE
    "\u202f",  # NARROW NO-BREAK SPACE
    "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
    "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",
]
LINE_SEPARATORS = [
    "\u2028",  # LINE SEPARATOR
    "\u2029",  # PARAGRAPH SEPARATOR
    "\u000b",  # VERTICAL TAB
    "\u000c",  # FORM FEED
]
SOFT_HYPHEN = "\u00ad"

BULLET_MAP = {
    "•": "-", "◦": "-", "∙": "-", "·": "-", "●": "-",
    "": "-", "": "-", "": "-", "–": "-", "—": "-",
}

def normalize_unicode(s: str) -> str:
    # 1) Chuẩn hoá tổ hợp dấu tiếng Việt về NFC
    s = unicodedata.normalize("NFC", s)
    # 2) Xoá soft hyphen
    s = s.replace(SOFT_HYPHEN, "")
    # 3) Gỡ ký tự vô hình
    for ch in INVISIBLE_CHARS:
        s = s.replace(ch, "")
    # 4) Chuẩn hoá khoảng trắng đặc biệt → space
    for ch in SPACE_LIKES:
        s = s.replace(ch, " ")
    # 5) Chuẩn hoá các dấu xuống dòng lạ → \n
    for ch in LINE_SEPARATORS:
        s = s.replace(ch, "\n")
    return s

def replace_bullets(s: str) -> str:
    return "".join(BULLET_MAP.get(ch, ch) for ch in s)

def collapse_spaces_and_lines(s: str) -> str:
    # Gom nhiều space thành một
    s = re.sub(r"[ \t]+", " ", s)
    # Xoá space đầu/cuối dòng
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    # Giới hạn nhiều dòng trống liên tiếp ≤ 2
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def join_hyphenated_linebreaks(s: str) -> str:
    # Nối từ bị "-" ở cuối dòng: "vận-\nchuyển" → "vậnchuyển"
    # \w của Python hỗ trợ Unicode letters khi dùng re.UNICODE (mặc định).
    return re.sub(r"(?<=\w)-\n(?=\w)", "", s)

def join_wrapped_lines_in_paragraph(s: str) -> str:
    # Nối các dòng trong cùng đoạn nếu dòng trước không kết thúc bằng dấu câu mạnh.
    # Hữu ích khi PDF xuống dòng giữa câu.
    def _merge(match: re.Match) -> str:
        before = match.group(1)
        after = match.group(2)
        # Nếu dòng kết thúc bằng dấu câu mạnh, giữ \n
        if re.search(r"[.!?:;…»”)]$", before):
            return before + "\n" + after
        # Ngược lại nối bằng space
        return before + " " + after
    # Áp dụng nhiều lần để giảm dần
    for _ in range(2):
        s = re.sub(r"(.*\S)\n(\S.*)", _merge, s)
    return s

def sort_blocks(blocks: List[Tuple]) -> List[Tuple]:
    # blocks: (x0, y0, x1, y1, text, block_no, block_type)
    # Sắp theo y0 rồi x0 để đọc từ trên xuống trái sang phải.
    return sorted(blocks, key=lambda b: (round(b[1], 1), round(b[0], 1)))

def extract_text_by_blocks(page) -> str:
    raw_blocks = page.get_text("blocks")
    if not raw_blocks:
        return ""
    blocks = sort_blocks(raw_blocks)
    lines: List[str] = []
    for b in blocks:
        if not isinstance(b, (list, tuple)) or len(b) < 5:
            continue
        txt = b[4] or ""
        txt = normalize_unicode(txt)
        txt = replace_bullets(txt)
        txt = join_hyphenated_linebreaks(txt)
        txt = collapse_spaces_and_lines(txt)
        if txt:
            lines.append(txt)
    # Chèn 1 dòng trống giữa các blocks để tách đoạn
    return "\n\n".join(lines)

def clean_page_text(text: str) -> str:
    text = normalize_unicode(text)
    text = replace_bullets(text)
    text = join_hyphenated_linebreaks(text)
    text = join_wrapped_lines_in_paragraph(text)
    text = collapse_spaces_and_lines(text)
    return text

# ---------- Main Converter ----------

def pdf_to_txt_vi(input_pdf: str, output_txt: Optional[str] = None,
                  prefer_blocks: bool = True) -> dict:
    """
    Chuyển PDF → TXT, xử lý tốt tiếng Việt & ký tự Unicode:
    - NFC normalize, gỡ ký tự vô hình, soft hyphen
    - Chuẩn hoá khoảng trắng, dòng
    - Nối từ bị gạch nối ở cuối dòng
    - Sắp xếp và ghép theo blocks để giữ trật tự cột (nếu prefer_blocks=True)
    """
    if not os.path.exists(input_pdf):
        raise FileNotFoundError(f"Không tìm thấy file PDF: {input_pdf}")

    if output_txt is None:
        base, _ = os.path.splitext(input_pdf)
        output_txt = base + ".txt"

    pages_out: List[str] = []

    with fitz.open(input_pdf) as doc:
        for i, page in enumerate(doc, start=1):
            if prefer_blocks:
                page_text = extract_text_by_blocks(page)
            else:
                # "text" mode, sau đó làm sạch
                page_text = page.get_text("text") or ""
                if not page_text.strip():
                    # fallback: blocks
                    page_text = extract_text_by_blocks(page)
                else:
                    page_text = clean_page_text(page_text)

            page_text = clean_page_text(page_text)
            pages_out.append(f"=== Page {i} ===\n{page_text}\n")

    full_text = "\n".join(pages_out).strip()

    with open(output_txt, "w", encoding="utf-8", newline="\n") as f:
        f.write(full_text)

    return {"text": full_text, "txt_path": output_txt}
