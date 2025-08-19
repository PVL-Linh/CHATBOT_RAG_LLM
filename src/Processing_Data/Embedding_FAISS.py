# # Embedding_FAISS.py
# import os, re, sys
# from typing import Dict, List
# from langchain_core.documents import Document
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain_community.vectorstores import FAISS
# from langchain_community.embeddings import HuggingFaceEmbeddings

# from all_path import path_Documents_folder
# from pdf_to_text import process_pdf_documents

# # ===== Thông số =====
# CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 900))
# CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 250))
# if CHUNK_OVERLAP >= CHUNK_SIZE:
#     CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)
# SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
# DOCS_DIR = "./Documents"
# # ===== Đường dẫn =====
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "../Data"))
# INDEX_DIR = os.path.abspath(os.path.join(BASE_DIR, "../FAISS_Vector"))


# EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_DIR", "./src/models/local_multilingual_e5_large")

# def _gpu_kwargs():
#     try:
#         import torch
#         return {"device": "cuda" if torch.cuda.is_available() else "cpu"}
#     except Exception:
#         return {"device": "cpu"}

# def _clean_text(s: str) -> str:
#     if not s:
#         return ""
#     s = re.sub(r"\s+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     s = re.sub(r"[ \t]{2,}", " ", s)
#     return s.strip()

# def _load_text_files(folder: str) -> Dict[str, str]:
#     """Đọc toàn bộ .txt và .csv trong thư mục làm corpus."""
#     data: Dict[str, str] = {}
#     folder = os.path.abspath(folder)
#     if not os.path.isdir(folder):
#         print(f"⚠️  Không tìm thấy thư mục: {folder}", file=sys.stderr)
#         return data

#     import csv
#     for fn in os.listdir(folder):
#         path = os.path.join(folder, fn)
#         if not os.path.isfile(path):
#             continue

#         if fn.lower().endswith(".txt"):
#             with open(path, "r", encoding="utf-8") as f:
#                 data[fn] = f.read()

#         elif fn.lower().endswith(".csv"):
#             rows = []
#             with open(path, "r", encoding="utf-8") as f:
#                 reader = csv.reader(f)
#                 for row in reader:
#                     rows.append(" | ".join(row))
#             data[fn] = "\n".join(rows)

#     print(f"📄 Loaded {len(data)} files (.txt, .csv) from {folder}")
#     return data

# def main():
#     os.makedirs(INDEX_DIR, exist_ok=True)

#     # ✅ B1: Convert PDF -> TXT (luôn chạy trước khi build FAISS)
#     process_pdf_documents(DOCS_DIR, DATA_DIR)

#     # ✅ B2: Load TXT/CSV để embed
#     raw = _load_text_files(DATA_DIR)
#     if not raw:
#         raise RuntimeError(f"Không có TXT/CSV trong {DATA_DIR}")

#     # ✅ B3: Build document list
#     docs: List[Document] = []
#     for fname, text in raw.items():
#         t = _clean_text(text)
#         if not t:
#             continue
#         content = f"passage: SOURCE_FILE={fname}\n{t}"
#         docs.append(Document(page_content=content, metadata={"source": fname, "page": -1}))

#     splitter = RecursiveCharacterTextSplitter(
#         chunk_size=CHUNK_SIZE,
#         chunk_overlap=CHUNK_OVERLAP,
#         separators=SEPARATORS,
#         add_start_index=True,
#     )
#     chunks = splitter.split_documents(docs)
#     for i, d in enumerate(chunks):
#         d.metadata["chunk_id"] = i
#         if not d.page_content.lower().startswith("passage:"):
#             d.page_content = "passage: " + d.page_content

#     emb = HuggingFaceEmbeddings(
#         model_name=EMBED_MODEL_NAME,
#         model_kwargs=_gpu_kwargs(),
#         encode_kwargs={"normalize_embeddings": True, "batch_size": int(os.environ.get("EMB_BATCH", 32))},
#     )

#     print(f"⚙️ Building FAISS… (chunks={len(chunks)}, size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")
#     vs = FAISS.from_documents(chunks, emb)
#     vs.save_local(INDEX_DIR)
#     print(f"✅ FAISS index saved at: {INDEX_DIR}")

# if __name__ == "__main__":
#     main()


# Embedding_FAISS.py
# Embedding_FAISS.py
import os
import re
import sys
from typing import Dict, List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings  # NEW

from all_path import path_Documents_folder  # nếu bạn dùng; có thể bỏ nếu không cần
from pdf_to_text import process_pdf_documents

# =======================
# Tham số
# =======================
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1200))       # khuyến nghị
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 300))  # khuyến nghị
if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
DOCS_DIR = "./Documents"  # thư mục PDF gốc (sẽ convert -> txt)

# =======================
# Đường dẫn
# =======================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "../Data"))          # nơi chứa .txt/.csv sau khi convert
INDEX_DIR = os.path.abspath(os.path.join(BASE_DIR, "../FAISS_Vector")) # nơi lưu FAISS index

EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_DIR", "./src/models/local_multilingual_e5_large")

# =======================
# Helpers
# =======================
def _select_device() -> str:
    """Chọn 'cuda' nếu có GPU, ngược lại 'cpu'."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            print(f"🟢 Using CUDA GPU: {gpu_name}")
            return "cuda"
        print("🟡 CUDA is not available → using CPU")
    except Exception as e:
        print(f"🟡 torch import failed ({e}) → using CPU")
    return "cpu"

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def _load_text_files(folder: str) -> Dict[str, str]:
    """Đọc toàn bộ .txt và .csv trong thư mục làm corpus."""
    data: Dict[str, str] = {}
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        print(f"⚠️  Không tìm thấy thư mục: {folder}", file=sys.stderr)
        return data

    import csv
    files = [fn for fn in os.listdir(folder) if os.path.isfile(os.path.join(folder, fn))]
    for fn in files:
        path = os.path.join(folder, fn)
        try:
            if fn.lower().endswith(".txt"):
                with open(path, "r", encoding="utf-8") as f:
                    data[fn] = f.read()
            elif fn.lower().endswith(".csv"):
                rows = []
                with open(path, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        rows.append(" | ".join(row))
                data[fn] = "\n".join(rows)
        except Exception as e:
            print(f"⚠️  Lỗi đọc file {fn}: {e}", file=sys.stderr)

    print(f"📄 Loaded {len(data)} files (.txt, .csv) from {folder}")
    return data

# =======================
# Main
# =======================
def main():
    os.makedirs(INDEX_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # B1) Convert PDF -> TXT (luôn chạy trước khi build FAISS)
    #    - pdf_to_text sẽ xử lý header/footer, table_mode theo bạn cấu hình ở đó.
    process_pdf_documents(DOCS_DIR, DATA_DIR)

    # B2) Load TXT/CSV để embed
    raw = _load_text_files(DATA_DIR)
    if not raw:
        raise RuntimeError(f"Không có TXT/CSV trong {DATA_DIR}")

    # B3) Build document list
    #  - KHÔNG nhét SOURCE_FILE vào page_content, chỉ để metadata để tránh model nhại lại.
    docs: List[Document] = []
    for fname, text in raw.items():
        t = _clean_text(text)
        if not t:
            continue
        docs.append(Document(page_content=t, metadata={"source": fname, "page": -1}))

    # B4) Chunking
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)
    for i, d in enumerate(chunks):
        d.metadata["chunk_id"] = i

    # B5) Embeddings (GPU nếu có)
    device = _select_device()
    batch = int(os.environ.get("EMB_BATCH", 32 if device == "cuda" else 8))

    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_NAME,
        model_kwargs={"device": device},  # KHÔNG truyền torch_dtype vào đây
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
    )

    # B6) Build & save FAISS
    print(f"⚙️ Building FAISS… (chunks={len(chunks)}, size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}, device={device}, batch={batch})")
    vs = FAISS.from_documents(chunks, emb)
    vs.save_local(INDEX_DIR)
    print(f"✅ FAISS index saved at: {INDEX_DIR}")

if __name__ == "__main__":
    main()
