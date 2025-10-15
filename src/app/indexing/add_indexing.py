from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Tuple, Dict

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from .config_indexing import build_embeddings
from .paths_indexing import dept_paths, rel_from_data_dir, list_txt_files_under
from .index_utils_indexing import load_faiss, save_faiss, faiss_exists
from .corpus_utils_indexing import clean_text, chunk_text_to_docs

# PDF converter trong dự án của bạn
from app.Processing_Data.pdf_to_text import process_pdf_documents


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return clean_text(f.read())
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            return clean_text(f.read())


def _copy_into(dst_dir: str, abs_src_file: str) -> str:
    """
    Copy file vào dst_dir, giữ nguyên basename. Trả về đường dẫn mới.
    """
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(abs_src_file))
    with open(abs_src_file, "rb") as src, open(dst, "wb") as out:
        out.write(src.read())
    return dst


def _stage_txts_for_pdf(data_dir: str, pdf_path: str) -> List[str]:
    """
    Convert 1 PDF -> nhiều .txt trong data_dir. Trả về danh sách relative paths mới sinh.
    """
    before = set(rel_from_data_dir(data_dir, p) for p in list_txt_files_under(data_dir))

    # Đưa PDF vào data_dir/_tmp_single_pdf để giữ cấu trúc sạch
    tmp_dir = os.path.join(data_dir, "_tmp_single_pdf")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_pdf = _copy_into(tmp_dir, pdf_path)

    # Convert
    process_pdf_documents(tmp_dir, data_dir)

    # Cleanup thô (không sao nếu fail)
    try:
        os.remove(tmp_pdf)
        os.rmdir(tmp_dir)
    except Exception:
        pass

    after = set(rel_from_data_dir(data_dir, p) for p in list_txt_files_under(data_dir))
    new_rel = sorted(list(after - before))
    return new_rel


def add_files_to_index(root: str, dept: str, paths: List[str]) -> None:
    """
    Thêm TXT/PDF vào index của 1 phòng ban. Tự tạo index nếu chưa có.
    """
    dept_dir, data_dir, index_dir, corpus_path, update_dir = dept_paths(root, dept)
    emb, device, batch = build_embeddings()

    # Chuẩn bị index
    vs: FAISS | None = None
    index_exists = faiss_exists(index_dir)
    if index_exists:
        vs = load_faiss(index_dir, emb)

    os.makedirs(update_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    staged_docs: List[Document] = []

    for p in paths:
        abs_p = os.path.abspath(p)
        suffix = Path(abs_p).suffix.lower()

        if suffix == ".pdf":
            # Lưu bản gốc PDF (audit) rồi convert
            _copy_into(update_dir, abs_p)
            rel_txts = _stage_txts_for_pdf(data_dir, abs_p)
            for rel in rel_txts:
                text = _read_text(os.path.join(data_dir, rel))
                if text:
                    staged_docs.extend(chunk_text_to_docs(text, rel))
                    print(f"➕ Staged (PDF→TXT): {rel}")
        elif suffix == ".txt":
            # Đảm bảo TXT nằm trong data_dir
            if not os.path.abspath(abs_p).startswith(os.path.abspath(data_dir)):
                copied = _copy_into(data_dir, abs_p)
                rel = rel_from_data_dir(data_dir, copied)
            else:
                rel = rel_from_data_dir(data_dir, abs_p)
            text = _read_text(os.path.join(data_dir, rel))
            if text:
                staged_docs.extend(chunk_text_to_docs(text, rel))
                print(f"➕ Staged: {rel}")
        else:
            print(f"⛔ Skipped (not .txt/.pdf): {abs_p}")

    if not staged_docs:
        print("ℹ️ No new documents to add.")
        return

    print(f"⚙️ Embedding & updating… (chunks={len(staged_docs)}, device={device}, batch={batch})")

    if vs is None:
        # tạo mới
        vs = FAISS.from_documents(staged_docs, emb)
    else:
        # cập nhật
        vs.add_documents(staged_docs)

    save_faiss(vs, index_dir)
    print(f"✅ Index saved at: {index_dir}")


# (tuỳ chọn) dùng riêng lẻ qua CLI đơn giản để test nhanh
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Add into dept FAISS index")
    parser.add_argument("--root", default="", help="Vectorstore root (default: config)")
    parser.add_argument("--dept", required=True, help="Department key, vd: hr")
    parser.add_argument("paths", nargs="+", help="File paths (.txt/.pdf)")
    args = parser.parse_args()
    add_files_to_index(args.root, args.dept, args.paths)
