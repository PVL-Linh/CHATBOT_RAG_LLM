import re

_SOURCE_TAG_PAT = re.compile(
    r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
    re.IGNORECASE,
)
_PATH_TAG_PAT = re.compile(
    r"\s*\[(?=[^\]]{0,240})(?:[A-Za-z]:)?[^|\]\n]+?\|[0-9]+\]",
    re.UNICODE,
)

_CODE_FENCE = re.compile(r"```(?:[\w-]+)?\s*([\s\S]*?)\s*```", re.MULTILINE)

def strip_citations(text: str) -> str:
    if not text:
        return text
    text = _SOURCE_TAG_PAT.sub("", text)
    text = _PATH_TAG_PAT.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()

def _tree_score(b: str) -> int:
    return (3 * len(re.findall(r'[├└│]', b)) + len(re.findall(r'\b\d+(?:\.\d+){1,3}\b', b)))

def cleanup_org_answer(text: str) -> str:
    if not text:
        return ""
    t = (text or "").strip()
    fences = _CODE_FENCE.findall(t)
    if fences:
        best = max(fences, key=_tree_score)
        body = best.strip()
    else:
        body = t.strip()
    body = re.sub(r"\bHNCS\b", "HCNS", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return f"```text\n{body}\n```"
