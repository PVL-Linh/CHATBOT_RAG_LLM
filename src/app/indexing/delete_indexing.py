from __future__ import annotations
import os, json
from typing import List, Dict, Tuple
from pathlib import Path

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from .config_indexing import build_embeddings
from .paths_indexing import dept_paths
from .index_utils_indexing import load_faiss, save_faiss, faiss_exists


def _norm_src(x: str) -> str:
    # Chuẩn hoá path dạng forward slash để so sánh nhất quán
    return (x or "").replace("\\", "/").strip("/")


def _filter_corpus_jsonl_inplace(corpus_path: str, drop_sources: set[str]) -> int:
    """
    Lọc corpus.jsonl ngay tại chỗ: xoá các record có metadata.source thuộc drop_sources.
    Trả về số dòng đã xoá.
    """
    p = Path(corpus_path)
    if not p.is_file():
        return 0

    kept_lines: List[str] = []
    removed = 0
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                meta = obj.get("metadata") or {}
                src = _norm_src(meta.get("source") or "")
                if src in drop_sources:
                    removed += 1
                    continue
                kept_lines.append(line)
            except Exception:
                # Nếu parse lỗi thì giữ lại để an toàn
                kept_lines.append(line)

    # Ghi lại
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fo:
        fo.writelines(kept_lines)
    tmp.replace(p)
    return removed


def delete_sources_from_index(root: str, dept: str, sources: List[str]) -> Dict:
    """
    Xoá toàn bộ chunks có metadata['source'] trùng các giá trị trong `sources`
    (các giá trị phải giống như trả về bởi /api/indexing/list).
    """
    # Lấy các đường dẫn chính theo phòng ban
    _dept_dir, _data_dir, index_dir, corpus_path, _update_dir = dept_paths(root, dept)

    # Chuẩn bị embedding + kiểm tra index
    emb, *_ = build_embeddings()
    if not faiss_exists(index_dir):
        return {
            "deleted_chunks": 0,
            "rebuild": False,
            "deleted_sources": [],
            "corpus_removed": 0,
            "message": f"Index not found at {index_dir}",
        }

    vs = load_faiss(index_dir, emb)

    # Chuẩn hoá danh sách nguồn cần xoá
    targets = {_norm_src(s) for s in (sources or []) if s}
    if not targets:
        return {"deleted_chunks": 0, "rebuild": False, "deleted_sources": [], "corpus_removed": 0}

    # Thu thập id cần xoá theo nguồn
    store_dict = getattr(vs.docstore, "_dict", {})
    to_delete_ids: List[str] = []
    id_to_src: Dict[str, str] = {}

    for _id, doc in store_dict.items():
        if not isinstance(doc, Document):
            continue
        src = _norm_src(doc.metadata.get("source") or "")
        id_to_src[_id] = src
        if src in targets:
            to_delete_ids.append(_id)

    if not to_delete_ids:
        return {"deleted_chunks": 0, "rebuild": False, "deleted_sources": [], "corpus_removed": 0}

    # Cố gắng gọi xoá trực tiếp
    deleted_ok = False
    try:
        res = vs.delete(ids=to_delete_ids)  # có thể trả về None/True/False tuỳ version
        deleted_ok = True if (res is None or res is True) else False
    except Exception as e:
        # fallback rebuild
        deleted_ok = False

    rebuild = False
    if not deleted_ok:
        # Rebuild tối thiểu với phần còn lại
        keep_docs = [doc for _id, doc in store_dict.items() if _id not in to_delete_ids and isinstance(doc, Document)]
        new_vs = FAISS.from_documents(keep_docs, vs.embedding_function)
        # ✅ THỨ TỰ ĐÚNG: (index_dir, vs)
        save_faiss(index_dir, new_vs)
        rebuild = True
    else:
        # ✅ THỨ TỰ ĐÚNG: (index_dir, vs)
        save_faiss(index_dir, vs)

    # Lọc corpus.jsonl tương ứng (nếu có)
    deleted_srcs = {id_to_src[_id] for _id in to_delete_ids if _id in id_to_src}
    removed_lines = 0
    if corpus_path:
        removed_lines = _filter_corpus_jsonl_inplace(corpus_path, deleted_srcs)

    return {
        "deleted_chunks": len(to_delete_ids),
        "rebuild": rebuild,
        "deleted_sources": sorted(list(deleted_srcs)),
        "corpus_removed": removed_lines,
    }
