# -*- coding: utf-8 -*-
from typing import List, Tuple, Optional
from langchain_core.documents import Document
from .config_hr import MAX_CHARS_CTX_HR as _MAX

def build_context(pairs: List[Tuple[Document, Optional[float]]], max_chars: int = _MAX) -> str:
    blocks, used = [], 0
    for d, _score in pairs:
        m = d.metadata or {}
        tag = f"[{m.get('source','?')}|{m.get('chunk_id',-1)}]"
        txt = (d.page_content or '').strip()
        piece = (f"{tag}\n{txt}\n").strip() + "\n"
        if used + len(piece) > max_chars and blocks:
            break
        blocks.append(piece); used += len(piece)
    return "\n---\n".join(blocks)
