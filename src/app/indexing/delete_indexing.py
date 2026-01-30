from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from .paths_indexing import dept_paths
from .index_utils_indexing import build_embeddings, load_faiss, save_faiss


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _rel_from(base: Path, target: Path) -> str:
    try:
        return str(target.relative_to(base)).replace("\\", "/")
    except Exception:
        return str(target).replace("\\", "/")


def _safe_load_faiss(index_dir: str, emb):
    try:
        return load_faiss(index_dir)              # kiểu mới: chỉ cần path
    except TypeError:
        try:
            return load_faiss(index_dir=index_dir, emb=emb)  # kiểu cũ
        except TypeError:
            return load_faiss(index_dir=index_dir)           # biến thể khác


def _safe_save_faiss(vs: FAISS, index_dir: str) -> None:
    try:
        save_faiss(index_dir, vs)
        return
    except TypeError:
        pass
    save_faiss(vs, index_dir)


def _list_doc_ids_by_sources(vs: FAISS, targets: List[str]) -> List[str]:
    want = set(s.replace("\\", "/").strip("/") for s in targets)
    ids: List[str] = []
    store = getattr(vs.docstore, "_dict", {})
    for _id, doc in store.items():
        if not isinstance(doc, Document):
            continue
        src = (doc.metadata or {}).get("source", "")
        src = str(src).replace("\\", "/").strip("/")
        if src in want:
            ids.append(_id)
    return ids


def _delete_ids(vs: FAISS, ids: List[str]) -> Tuple[int, bool]:
    if not ids:
        return 0, False

    deleted_ok = False
    try:
        res = vs.delete(ids=ids)
        deleted_ok = (res is None) or (res is True)
    except Exception:
        deleted_ok = False

    if not deleted_ok:
        store = getattr(vs.docstore, "_dict", {})
        keep_docs = [doc for _id, doc in store.items() if _id not in ids and isinstance(doc, Document)]
        new_vs = FAISS.from_documents(keep_docs, vs.embedding_function)
        return len(ids), True, new_vs

    return len(ids), False, vs


def _project_root_from_vector_root(vector_root: Path) -> Path:
    try:
        return vector_root.resolve().parents[2]
    except Exception:
        return vector_root.resolve().parent.parent


def delete_sources_from_index(root: str, dept: str, sources: List[str]) -> Dict:
    if not sources:
        return {"deleted_chunks": 0, "moved_files": 0, "archive_dir": None, "rebuild": 0}

    _dept_dir, data_dir, index_dir, _corpus, _update_dir = dept_paths(root, dept)
    emb, _device, _batch = build_embeddings()
    vs = _safe_load_faiss(index_dir=str(index_dir), emb=emb)
    to_delete_ids = _list_doc_ids_by_sources(vs, sources)
    deleted_chunks = 0
    rebuilt = 0

    if to_delete_ids:
        try:
            res = vs.delete(ids=to_delete_ids)
            deleted_ok = (res is None) or (res is True)
        except Exception:
            deleted_ok = False

        if not deleted_ok:
            store = getattr(vs.docstore, "_dict", {})
            keep_docs = [doc for _id, doc in store.items() if _id not in to_delete_ids and isinstance(doc, Document)]
            vs = FAISS.from_documents(keep_docs, vs.embedding_function)
            rebuilt = 1

        deleted_chunks = len(to_delete_ids)

    _safe_save_faiss(vs, str(index_dir))

    vector_root = Path(root)
    project_root = _project_root_from_vector_root(vector_root)
    archive_root = project_root / "_deleted" / str(dept)
    _ensure_dir(archive_root)

    moved = 0
    data_dir_p = Path(data_dir)
    for rel in sources:
        rel_norm = rel.replace("\\", "/").strip("/")
        src_path = data_dir_p / rel_norm
        if src_path.is_file():
            dst_path = archive_root / rel_norm
            _ensure_dir(dst_path.parent)
            try:
                shutil.move(str(src_path), str(dst_path))
                moved += 1
            except Exception:
                pass

    return {
        "deleted_chunks": int(deleted_chunks),
        "rebuild": int(rebuilt),
        "moved_files": int(moved),
        "archive_dir": str(archive_root),
    }
