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

_CODEBLOCK_RE = re.compile(r"```(\w+)?\s*\n([\s\S]*?)\n```", re.MULTILINE)
_CODE_FENCE = re.compile(r"```(?:[\w-]+)?\s*([\s\S]*?)\s*```", re.MULTILINE)
_TREE_SCORE = lambda b: (3*len(re.findall(r"[├└│]", b)) +
                         len(re.findall(r"\b\d+(?:\.\d+){1,3}\b", b)))
def strip_citations(text: str) -> str:
    if not text:
        return text
    text = _SOURCE_TAG_PAT.sub("", text)
    text = _PATH_TAG_PAT.sub("", text)
    # dọn khoảng trắng
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()

def _normalize_block(s: str) -> str:
    """Chuẩn hoá để so sánh nội dung block: bỏ khoảng trắng thừa đầu/cuối dòng."""
    lines = [ln.rstrip() for ln in (s or "").splitlines()]
    # gộp nhiều dòng trống liên tiếp
    out, blank = [], False
    for ln in lines:
        if ln.strip() == "":
            if not blank:
                out.append("")
                blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()

def dedupe_code_blocks(md: str, prefer_lang: str = "text") -> str:
    """
    - Xoá các code block trùng nội dung (giữ block đầu tiên).
    - Ép block đầu tiên không có lang thành ```text.
    """
    if not md:
        return md

    matches = list(_CODEBLOCK_RE.finditer(md))
    if not matches:
        return md

    # Tính span các block để xoá chính xác
    to_delete = set()
    seen = set()
    first_plain_start = None
    first_plain_end = None
    first_plain_content = None

    for i, m in enumerate(matches):
        lang = (m.group(1) or "").strip().lower()
        content = m.group(2) or ""
        norm = _normalize_block(content)
        if norm in seen:
            to_delete.add(i)
        else:
            seen.add(norm)
            # ghi nhớ block đầu tiên không có lang để đổi sang ```text
            if not lang and first_plain_start is None:
                first_plain_start, first_plain_end = m.span(0)
                first_plain_content = content

    # Xoá block trùng (từ phải sang trái để không lệch chỉ số)
    out = md
    for i in sorted(to_delete, reverse=True):
        s, e = matches[i].span(0)
        out = out[:s] + out[e:]

    # Ép block đầu không có lang -> ```text
    if first_plain_start is not None and prefer_lang:
        before = out[:first_plain_start]
        block = out[first_plain_start:first_plain_end]
        after = out[first_plain_end:]

        # thay ```\n...``` thành ```text\n...```
        block = re.sub(r"^```(\s*\n)", f"```{prefer_lang}\\1", block)
        out = before + block + after

    return out

def fix_common_org_typos(s: str) -> str:
    if not s:
        return s
    # HNCS -> HCNS (lỗi chính tả phổ biến)
    s = re.sub(r"\bHNCS\b", "HCNS", s)
    return s

def cleanup_org_answer(text: str) -> str:
    """
    - Nếu có nhiều code-fence: chọn block 'tree' nhất (nhiều ├└│ / chỉ mục 1.2.3).
    - Nếu không có fence: bao toàn bộ vào 1 fence.
    - Sửa 'HNCS' -> 'HCNS', khử whitespace thừa.
    - Trả về DUY NHẤT 1 fence loại ```text
    """
    if not text:
        return ""

    t = (text or "").strip()
    fences = _CODE_FENCE.findall(t)

    if fences:
        # chọn block 'tree' nhất; nếu bằng điểm, lấy block xuất hiện trước
        best = max(fences, key=_TREE_SCORE)
        body = best.strip()
    else:
        body = t.strip()

    # chuẩn hoá minor
    body = re.sub(r"\bHNCS\b", "HCNS", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return f"```text\n{body}\n```"