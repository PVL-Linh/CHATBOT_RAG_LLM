from .index_utils_indexing import load_faiss, faiss_exists
from .paths_indexing import dept_paths
from langchain_core.documents import Document

def list_index_sources(root: str, dept: str):
    _dept_dir, _data_dir, index_dir, _corpus, _update = dept_paths(root, dept)
    if not faiss_exists(index_dir):
        return []
    vs = load_faiss(index_dir)  # hoặc load_faiss(index_dir, emb=None)
    store = getattr(vs.docstore, "_dict", {})
    counter = {}
    for _id, doc in store.items():
        if isinstance(doc, Document):
            src = (doc.metadata or {}).get("source") or ""
            counter[src] = counter.get(src, 0) + 1
    return sorted(counter.items(), key=lambda kv: kv[0])
