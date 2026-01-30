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
from langchain_community.embeddings import HuggingFaceEmbeddings
try:
    from app.Processing_Data.pdf_to_text import process_pdf_documents
except Exception:
    process_pdf_documents = None

try:
    from app.Processing_Data.xlxs_to_csv import xlsx_to_txt_by_column_all_sheets
except Exception:
    xlsx_to_txt_by_column_all_sheets = None
    
from .paths_indexing import dept_paths, list_txt_files_under, rel_from_data_dir
from .config_indexing import CHUNK_OVERLAP, CHUNK_SIZE

if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

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

def _safe_read_text(path: str)  -> str:
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

def add_files_to_index(root: str, dept: str, paths: List[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": True,
        "added_files": [],
        "added_chunks": 0,
        "skipped_duplicates": [],
        "skipped_invalid": [],
        "errors": [],
    }

    dept_dir, data_dir, index_dir, corpus_path, update_dir = dept_paths(root, dept)
    os.makedirs(data_dir, exist_ok=True)

    existed_lower = _existing_basenames_lower(data_dir)
    staged_rel_txts: List[str] = []
    seen_in_batch: set = set()

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

            if not os.path.abspath(p_abs).startswith(os.path.abspath(data_dir) + os.sep):
                dst = os.path.join(data_dir, base)
                try:
                    shutil.copy2(p_abs, dst)
                except Exception as e:
                    result["errors"].append(f"Copy TXT lỗi: {base} → {e}")
                    continue
                rel = rel_from_data_dir(dst, data_dir)
            else:
                rel = rel_from_data_dir(p_abs, data_dir)

            staged_rel_txts.append(rel)
            seen_in_batch.add(base_l)

        elif ext == ".pdf":
            if process_pdf_documents is None:
                result["skipped_invalid"].append(p)
                result["errors"].append("Chưa cấu hình converter PDF→TXT; từ chối PDF.")
                continue

            before = set(os.path.abspath(x) for x in list_txt_files_under(data_dir))

            tmp_dir = os.path.join(data_dir, "_tmp_pdf_input")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_pdf = os.path.join(tmp_dir, os.path.basename(p_abs))
            try:
                shutil.copy2(p_abs, tmp_pdf)
            except Exception as e:
                result["errors"].append(f"Copy PDF lỗi: {os.path.basename(p_abs)} → {e}")
                try:
                    if os.path.exists(tmp_pdf):
                        os.remove(tmp_pdf)
                    if os.path.isdir(tmp_dir) and not os.listdir(tmp_dir):
                        os.rmdir(tmp_dir)
                except Exception:
                    pass
                continue

            try:
                process_pdf_documents(tmp_dir, data_dir)
            except Exception as e:
                result["errors"].append(f"Chuyển PDF→TXT lỗi: {os.path.basename(p_abs)} → {e}")

            try:
                if os.path.exists(tmp_pdf):
                    os.remove(tmp_pdf)
                if os.path.isdir(tmp_dir) and not os.listdir(tmp_dir):
                    os.rmdir(tmp_dir)
            except Exception:
                pass

            after = set(os.path.abspath(x) for x in list_txt_files_under(data_dir))
            new_txt_abs = sorted(after - before)

            for txt_path in new_txt_abs:
                base = os.path.basename(txt_path)
                base_l = base.lower()
                if (base_l in existed_lower) or (base_l in seen_in_batch):
                    result["skipped_duplicates"].append(base)
                    try:
                        os.remove(txt_path)
                    except Exception:
                        pass
                    continue
                rel = rel_from_data_dir(txt_path, data_dir)
                staged_rel_txts.append(rel)
                seen_in_batch.add(base_l)
        elif ext == ".xlsx":
            if xlsx_to_txt_by_column_all_sheets is None:
                result["skipped_invalid"].append(p_abs)
                result["errors"].append("Chưa cấu hình converter XLSX→TXT; từ chối XLSX.")
                continue

            # Ghi nhận list TXT trước khi convert
            before = set(os.path.abspath(x) for x in list_txt_files_under(data_dir))

            try:
                # Convert 1 file .xlsx -> nhiều .txt (mỗi sheet 1 file)
                # Output_dir = data_dir để sau đó rel_from_data_dir dùng chung logic
                xlsx_to_txt_by_column_all_sheets(p_abs, data_dir)
            except Exception as e:
                result["errors"].append(f"Chuyển XLSX→TXT lỗi: {os.path.basename(p_abs)} → {e}")
                continue

            # Lấy các TXT mới sinh ra
            after = set(os.path.abspath(x) for x in list_txt_files_under(data_dir))
            new_txt_abs = sorted(after - before)

            for txt_path in new_txt_abs:
                base = os.path.basename(txt_path)
                base_l = base.lower()
                if (base_l in existed_lower) or (base_l in seen_in_batch):
                    result["skipped_duplicates"].append(base)
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

    if not staged_rel_txts:
        return result
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
