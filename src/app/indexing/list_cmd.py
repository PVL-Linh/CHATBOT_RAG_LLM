from __future__ import annotations
from typing import List, Tuple, Dict
import unicodedata

from langchain_core.documents import Document

from .config_indexing import build_embeddings
from .paths_indexing import dept_paths
from .index_utils_indexing import load_faiss, faiss_exists


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _norm(s: str) -> str:
    return _nfc(str(s)).replace("\\", "/")


def list_index_sources(root: str, dept: str) -> List[Tuple[str, int]]:
    _dept_dir, _data_dir, index_dir, _corpus, _update = dept_paths(root, dept)
    emb, *_ = build_embeddings()
    if not faiss_exists(index_dir):
        return []
    vs = load_faiss(index_dir, emb)
    counter: Dict[str, int] = {}
    for _id, doc in getattr(vs.docstore, "_dict", {}).items():
        if isinstance(doc, Document):
            src = _norm(doc.metadata.get("source", ""))
            if src:
                counter[src] = counter.get(src, 0) + 1
    return sorted(counter.items(), key=lambda kv: kv[0])
