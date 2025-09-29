import re

# cũ: chỉ bắt 'source|chunk' -> KHÔNG đủ
# mới: thêm pattern bắt mọi dạng [<đường_dẫn> | <số>] ngắn
_SOURCE_TAG_PAT = re.compile(
    r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
    re.IGNORECASE,
)
_PATH_TAG_PAT = re.compile(
    r"\s*\[(?=[^\]]{0,240})(?:[A-Za-z]:)?[^|\]\n]+?\|[0-9]+\]",  # [Diagram\...\|27]
    re.UNICODE,
)

def strip_citations(text: str) -> str:
    if not text:
        return text
    text = _SOURCE_TAG_PAT.sub("", text)
    text = _PATH_TAG_PAT.sub("", text)
    # dọn khoảng trắng
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()
