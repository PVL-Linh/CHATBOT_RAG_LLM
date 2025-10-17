from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# các util sẵn có của bạn
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
    """
    Một số phiên bản bạn đang dùng có chữ ký load_faiss(index_dir) hoặc load_faiss(index_dir=..., emb=...).
    Hàm này gọi linh hoạt để không vấp lỗi 'unexpected keyword'.
    """
    try:
        return load_faiss(index_dir)              # kiểu mới: chỉ cần path
    except TypeError:
        try:
            return load_faiss(index_dir=index_dir, emb=emb)  # kiểu cũ
        except TypeError:
            return load_faiss(index_dir=index_dir)           # biến thể khác


def _safe_save_faiss(vs: FAISS, index_dir: str) -> None:
    """
    Bạn gặp lỗi vì chữ ký save_faiss() ở dự án hiện tại có thể là:
      - save_faiss(index_dir, vs)  (tham số thứ nhất tên 'index_dir')
      - hoặc save_faiss(vs, index_dir)
    Gọi thử theo thứ tự an toàn để tránh 'multiple values for argument'.
    """
    try:
        # TH1: chữ ký (index_dir, vs)
        save_faiss(index_dir, vs)   # positional, không đặt tên
        return
    except TypeError:
        pass
    # TH2: chữ ký (vs, index_dir)
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
    """
    Cố gắng xoá bằng vs.delete(ids=...). Nếu version không hỗ trợ, rebuild nhẹ.
    Return: (deleted_count, rebuilt_flag)
    """
    if not ids:
        return 0, False

    deleted_ok = False
    try:
        res = vs.delete(ids=ids)         # tuỳ version: None/True/False
        deleted_ok = (res is None) or (res is True)
    except Exception:
        deleted_ok = False

    if not deleted_ok:
        # Rebuild giữ lại phần còn lại
        store = getattr(vs.docstore, "_dict", {})
        keep_docs = [doc for _id, doc in store.items() if _id not in ids and isinstance(doc, Document)]
        new_vs = FAISS.from_documents(keep_docs, vs.embedding_function)
        return len(ids), True, new_vs

    return len(ids), False, vs


def _project_root_from_vector_root(vector_root: Path) -> Path:
    """
    root bạn truyền vào hiện là .../src/app/vectorstore
    => project root mong muốn là .../ChatAll
    """
    # vector_root = E:\ChatAll\src\app\vectorstore
    # parents[0]=.../src/app, parents[1]=.../src, parents[2]=.../ChatAll
    try:
        return vector_root.resolve().parents[2]
    except Exception:
        # fallback: về 2 cấp
        return vector_root.resolve().parent.parent


def delete_sources_from_index(root: str, dept: str, sources: List[str]) -> Dict:
    """
    Xoá toàn bộ chunks có metadata['source'] trùng các 'sources' (đường dẫn tương đối tính từ data_dir),
    cập nhật lại FAISS, và di chuyển file gốc sang thư mục archive ngoài app:
      <PROJECT_ROOT>/_deleted/<DEPT>/...
    """
    if not sources:
        return {"deleted_chunks": 0, "moved_files": 0, "archive_dir": None, "rebuild": 0}

    # Lấy đường dẫn theo dept
    # dept_paths phải trả tuple: (dept_dir, data_dir, index_dir, corpus, update_dir)
    _dept_dir, data_dir, index_dir, _corpus, _update_dir = dept_paths(root, dept)

    # Build embedding + load FAISS linh hoạt
    emb, _device, _batch = build_embeddings()
    vs = _safe_load_faiss(index_dir=str(index_dir), emb=emb)

    # Xoá trong FAISS
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
            # Rebuild giữ phần còn lại
            store = getattr(vs.docstore, "_dict", {})
            keep_docs = [doc for _id, doc in store.items() if _id not in to_delete_ids and isinstance(doc, Document)]
            vs = FAISS.from_documents(keep_docs, vs.embedding_function)
            rebuilt = 1

        deleted_chunks = len(to_delete_ids)

    # Lưu FAISS (gọi an toàn cho mọi chữ ký)
    _safe_save_faiss(vs, str(index_dir))

    # Di chuyển file vật lý sang archive ngoài app
    vector_root = Path(root)  # .../src/app/vectorstore
    project_root = _project_root_from_vector_root(vector_root)  # .../ChatAll
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
                # nếu file đang bị lock hoặc không di chuyển được thì bỏ qua
                pass

    return {
        "deleted_chunks": int(deleted_chunks),
        "rebuild": int(rebuilt),
        "moved_files": int(moved),
        "archive_dir": str(archive_root),
    }
