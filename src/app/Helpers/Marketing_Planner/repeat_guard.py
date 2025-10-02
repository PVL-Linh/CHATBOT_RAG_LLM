# Helpers/repeat_guard.py
import re

_SENT_SPLIT = re.compile(r"(?<=[\.\!\?…])\s+(?=[A-ZÀ-Ỵ])", re.U)

def _norm(s: str) -> str:
    s = s or ""
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def jaccard_sentence_overlap(a: str, b: str) -> float:
    """Đo trùng lặp theo tập câu (Jaccard)."""
    if not a or not b:
        return 0.0
    sa = set(map(_norm, _SENT_SPLIT.split(a)))
    sb = set(map(_norm, _SENT_SPLIT.split(b)))
    sa.discard(""); sb.discard("")
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / max(1, union)

def dedup_paragraphs(base: str, addition: str, overlap_threshold: float = 0.55) -> str:
    """Loại bỏ đoạn mới nếu trùng ý với base quá cao."""
    base = base or ""
    addition = addition or ""
    paras = [p.strip() for p in re.split(r"\n{2,}", addition) if p.strip()]
    kept = []
    for p in paras:
        ov = jaccard_sentence_overlap(base, p)
        if ov < overlap_threshold:
            kept.append(p)
    return ("\n\n".join(kept)).strip()
