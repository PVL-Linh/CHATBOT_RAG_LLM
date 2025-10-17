from __future__ import annotations
import os
import re
import sys
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

# Tuỳ dự án của bạn: nếu có hàm chuyển PDF → TXT sẵn, import vào đây
try:
    # ví dụ: từ module của bạn
    from app.pdf.pdf_to_text import process_pdf_documents  # type: ignore
except Exception:
    # Nếu chưa có, để None: PDF sẽ bị từ chối với thông báo rõ ràng
    process_pdf_documents = None  # type: ignore

from .paths_indexing import dept_paths, list_txt_files_under, rel_from_data_dir

# ============= Cấu hình cắt/ghép =============
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "300"))
if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# ============= Utils =============
def _select_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"

def _build_embeddings():
    device = _select_device()
    # batch lớn hơn trên GPU
    batch = 32 if device == "cuda" else 8
    model_name = os.environ.get(
        "EMBED_MODEL_DIR", "./src/app/models/local_multilingual_e5_large"
    )
    emb = HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
    )
    return emb, device, batch

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def _chunk_text_to_docs(text: str, rel_source: str) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        add_start_index=True,
    )
    docs = [Document(page_content=text, metadata={"source": rel_source, "page": -1})]
    chunks = splitter.split_documents(docs)
    for i, d in enumerate(chunks):
        d.metadata["chunk_id"] = i
    return chunks

def _safe_read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _clean_text(f.read())
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            return _clean_text(f.read())

def _existing_basenames_lower(data_dir: str) -> set:
    """Lấy set tên file (basename) đã tồn tại trong data_dir, in lowercase."""
    result = set()
    for p in list_txt_files_under(data_dir):
        result.add(os.path.basename(p).lower())
    return result

def _load_faiss(index_dir: str, emb: HuggingFaceEmbeddings) -> FAISS:
    if not os.path.isdir(index_dir):
        raise RuntimeError(f"FAISS index chưa được khởi tạo tại: {index_dir}")
    return FAISS.load_local(index_dir, emb, allow_dangerous_deserialization=True)

def _save_faiss(vs: FAISS, index_dir: str):
    os.makedirs(index_dir, exist_ok=True)
    vs.save_local(index_dir)

# ============= HÀM CHÍNH =============
def add_files_to_index(root: str, dept: str, paths: List[str]) -> Dict[str, Any]:
    """
    Thêm file TXT/PDF vào index phòng ban, với quy tắc:
      - Nếu trùng tên (basename, không phân biệt hoa/thường) với file đã có trong data_dir => KHÔNG thêm.
      - PDF: cần có process_pdf_documents. Các TXT sinh ra nếu trùng tên cũng bị bỏ qua.
    Trả về:
      {
        "ok": True/False,
        "added_files": [rel_txt, ...],
        "added_chunks": int,
        "skipped_duplicates": [basename, ...],
        "skipped_invalid": [path, ...],
        "errors": [message, ...]
      }
    """
    result: Dict[str, Any] = {
        "ok": True,
        "added_files": [],
        "added_chunks": 0,
        "skipped_duplicates": [],
        "skipped_invalid": [],
        "errors": [],
    }

    # Lấy đường dẫn phòng ban
    dept_dir, data_dir, index_dir, corpus_path, update_dir = dept_paths(root, dept)
    os.makedirs(data_dir, exist_ok=True)

    # Tập tên đã có
    existed_lower = _existing_basenames_lower(data_dir)
    staged_rel_txts: List[str] = []
    seen_in_batch: set = set()  # tránh trùng trong chính batch upload

    # 1) Chuẩn bị TXT (copy vào data_dir nếu đang ở ngoài) + chặn trùng tên
    for p in paths:
        if not p:
            continue
        p_abs = os.path.abspath(p)
        ext = Path(p_abs).suffix.lower()

        if ext == ".txt":
            base = os.path.basename(p_abs)
            base_l = base.lower()

            if (base_l in existed_lower) or (base_l in seen_in_batch):
                result["skipped_duplicates"].append(base)
                continue

            # Copy vào data_dir nếu file ở ngoài
            if not os.path.abspath(p_abs).startswith(os.path.abspath(data_dir) + os.sep):
                dst = os.path.join(data_dir, base)
                try:
                    shutil.copy2(p_abs, dst)
                except Exception as e:
                    result["errors"].append(f"Copy TXT lỗi: {base} → {e}")
                    continue
                rel = rel_from_data_dir(dst, data_dir)
            else:
                # đã nằm trong data_dir
                rel = rel_from_data_dir(p_abs, data_dir)

            staged_rel_txts.append(rel)
            seen_in_batch.add(base_l)

        elif ext == ".pdf":
            if process_pdf_documents is None:
                result["skipped_invalid"].append(p)
                result["errors"].append("Chưa cấu hình converter PDF→TXT; từ chối PDF.")
                continue

            # Snapshot trước
            before = set(os.path.abspath(x) for x in list_txt_files_under(data_dir))

            # Đặt PDF tạm trong thư mục riêng để converter xử lý
            tmp_dir = os.path.join(data_dir, "_tmp_pdf_input")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_pdf = os.path.join(tmp_dir, os.path.basename(p_abs))
            try:
                shutil.copy2(p_abs, tmp_pdf)
            except Exception as e:
                result["errors"].append(f"Copy PDF lỗi: {os.path.basename(p_abs)} → {e}")
                # dọn rác tạm
                try:
                    if os.path.exists(tmp_pdf):
                        os.remove(tmp_pdf)
                    if os.path.isdir(tmp_dir) and not os.listdir(tmp_dir):
                        os.rmdir(tmp_dir)
                except Exception:
                    pass
                continue

            # Chạy converter
            try:
                process_pdf_documents(tmp_dir, data_dir)  # tạo ra TXT trong data_dir
            except Exception as e:
                result["errors"].append(f"Chuyển PDF→TXT lỗi: {os.path.basename(p_abs)} → {e}")

            # dọn rác tạm
            try:
                if os.path.exists(tmp_pdf):
                    os.remove(tmp_pdf)
                if os.path.isdir(tmp_dir) and not os.listdir(tmp_dir):
                    os.rmdir(tmp_dir)
            except Exception:
                pass

            # TXT mới sinh ra
            after = set(os.path.abspath(x) for x in list_txt_files_under(data_dir))
            new_txt_abs = sorted(after - before)

            for txt_path in new_txt_abs:
                base = os.path.basename(txt_path)
                base_l = base.lower()
                if (base_l in existed_lower) or (base_l in seen_in_batch):
                    result["skipped_duplicates"].append(base)
                    # nếu trùng thì xoá luôn bản TXT vừa sinh để tránh bẩn data_dir
                    try:
                        os.remove(txt_path)
                    except Exception:
                        pass
                    continue
                rel = rel_from_data_dir(txt_path, data_dir)
                staged_rel_txts.append(rel)
                seen_in_batch.add(base_l)

        else:
            result["skipped_invalid"].append(p_abs)

    # Không có gì để thêm
    if not staged_rel_txts:
        # Nếu không có lỗi nào khác, vẫn ok=True nhưng added=0; frontend nên báo rõ duplicate/invalid
        return result

    # 2) Đọc nội dung + chunk
    docs: List[Document] = []
    for rel in staged_rel_txts:
        txt_abs = os.path.join(data_dir, rel.replace("/", os.sep))
        try:
            text = _safe_read_text(txt_abs)
            if not text:
                continue
            docs.extend(_chunk_text_to_docs(text, rel))
        except Exception as e:
            result["errors"].append(f"Đọc TXT lỗi: {rel} → {e}")

    if not docs:
        return result

    # 3) Load FAISS + add
    emb, device, batch = _build_embeddings()
    try:
        vs = _load_faiss(index_dir, emb)
    except Exception as e:
        result["ok"] = False
        result["errors"].append(f"Không thể load FAISS index ({index_dir}): {e}")
        return result

    try:
        vs.add_documents(docs)
        _save_faiss(vs, index_dir)
        result["added_files"] = staged_rel_txts
        result["added_chunks"] = len(docs)
    except Exception as e:
        result["ok"] = False
        result["errors"].append(f"Lỗi khi thêm vào FAISS: {e}")

    return result
