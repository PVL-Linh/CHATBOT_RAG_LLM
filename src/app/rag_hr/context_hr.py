from typing import List, Tuple, Optional
from langchain_core.documents import Document
from .config_hr import MAX_CHARS_CTX

def build_context(pairs: List[Tuple[Document, Optional[float]]], max_chars: int = MAX_CHARS_CTX) -> str:
    blocks, used = [], 0
    for d, score in pairs:
        meta = d.metadata or {}
        tag = f"[{meta.get('source', '?')}|{meta.get('chunk_id', -1)}]"
        text = (d.page_content or '').strip()
        piece = (f"{tag}\n{text}\n").strip() + "\n"
        if used + len(piece) > max_chars and blocks:
            break
        blocks.append(piece)
        used += len(piece)
    return "\n---\n".join(blocks)
