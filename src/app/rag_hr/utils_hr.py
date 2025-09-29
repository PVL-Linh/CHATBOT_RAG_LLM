import re
import unicodedata

def select_device() -> str:
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def clip(s: str, n: int) -> str:
    s = (s or "").replace("\u0000", " ").replace("\r", " ")
    return (s[:n] + "…") if len(s) > n else s

def normalize_case(s: str, mode: str = "lower") -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower() if mode == "lower" else s.upper()

def clean_text(s: str) -> str:
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def split_text(text: str, chunk_size=1200, overlap=300):
    parts = []
    paragraphs = re.split(r"\n{2,}", text)
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        start = 0
        while start < len(p):
            end = min(len(p), start + chunk_size)
            parts.append(p[start:end])
            if end == len(p):
                break
            start = max(end - overlap, 0)
    return parts
