import re
from .config_hr import STRIP_CITATIONS

# Bỏ mọi thẻ [anything|digits] – ví dụ: [file\path.txt|28]
_CIT_PAT = re.compile(r"\[[^\[\]]+\|\d+\]")

def strip_citations(text: str) -> str:
    if not STRIP_CITATIONS:
        return text
    if not text:
        return text
    text = _CIT_PAT.sub("", text)
    # sạch khoảng trắng
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()
