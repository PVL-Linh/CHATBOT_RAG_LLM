import fitz
import os
import re
import unicodedata
from typing import List, Tuple, Optional

INVISIBLE_CHARS = [
    "\u200b",
    "\u200c",
    "\u200d",
    "\ufeff",
    "\u2060",
]
SPACE_LIKES = [
    "\u00a0",
    "\u202f",
    "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
    "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",
]
LINE_SEPARATORS = [
    "\u2028",
    "\u2029",
    "\u000b",
    "\u000c",
]
SOFT_HYPHEN = "\u00ad"

BULLET_MAP = {
    "•": "-", "◦": "-", "∙": "-", "·": "-", "●": "-",
    "": "-", "": "-", "": "-", "–": "-", "—": "-",
}

def normalize_unicode(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace(SOFT_HYPHEN, "")
    for ch in INVISIBLE_CHARS:
        s = s.replace(ch, "")
    for ch in SPACE_LIKES:
        s = s.replace(ch, " ")
    for ch in LINE_SEPARATORS:
        s = s.replace(ch, "\n")
    return s

def replace_bullets(s: str) -> str:
    return "".join(BULLET_MAP.get(ch, ch) for ch in s)

def collapse_spaces_and_lines(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def join_hyphenated_linebreaks(s: str) -> str:
    return re.sub(r"(?<=\w)-\n(?=\w)", "", s)

def join_wrapped_lines_in_paragraph(s: str) -> str:
    def _merge(match: re.Match) -> str:
        before = match.group(1)
        after = match.group(2)
        if re.search(r"[.!?:;…»”)]$", before):
            return before + "\n" + after
        return before + " " + after

    for _ in range(2):
        s = re.sub(r"(.*\S)\n(\S.*)", _merge, s)
    return s

def sort_blocks(blocks: List[Tuple]) -> List[Tuple]:
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
    return "\n\n".join(lines)

def clean_page_text(text: str) -> str:
    text = normalize_unicode(text)
    text = replace_bullets(text)
    text = join_hyphenated_linebreaks(text)
    text = join_wrapped_lines_in_paragraph(text)
    text = collapse_spaces_and_lines(text)
    return text

def pdf_to_txt_vi(input_pdf: str, output_txt: Optional[str] = None,
                  prefer_blocks: bool = True) -> dict:

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
                page_text = page.get_text("text") or ""
                if not page_text.strip():
                    page_text = extract_text_by_blocks(page)
                else:
                    page_text = clean_page_text(page_text)

            page_text = clean_page_text(page_text)
            pages_out.append(f"=== Page {i} ===\n{page_text}\n")

    full_text = "\n".join(pages_out).strip()

    with open(output_txt, "w", encoding="utf-8", newline="\n") as f:
        f.write(full_text)

    return {"text": full_text, "txt_path": output_txt}
