import os
import re
import sys
from typing import Dict, List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings 
from pdf_to_text import process_documents
import torch
try:
    from .Prosessing_HR.pdf_to_text_HR import processing_Data_doclinkToText, processing_Data_dockinkToText_v2
    from .DataBase_Web.web_crawler import web_crawler
except ImportError:
    from DataBase_Web.web_crawler import web_crawler
    from Prosessing_HR.pdf_to_text_HR import processing_Data_doclinkToText, processing_Data_dockinkToText_v2

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 250))
if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
DOCS_DIR = "./Documents/Data_All"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "../Data/Data_All"))
INDEX_DIR = os.path.abspath(os.path.join(BASE_DIR, "../vectorstore/FAISS_Vector_All"))
EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_DIR", "./src/app/models/local_multilingual_e5_large")

def _select_device() -> str:
    if torch.backends.mps.is_available():
        print("🟢 Using MPS (Apple GPU)")
        return "mps"
    elif torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        print(f"🟢 Using CUDA GPU: {gpu_name}")
        return "cuda"
    else:
        print("🟡 Defaulting to CPU")
        return "cpu"

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def _load_text_files(folder: str) -> Dict[str, str]:
    """
    Đọc đệ quy toàn bộ *.txt trong `folder`, bỏ qua mọi file tên 'urls.txt'.
    Trả về dict: {relative_path: text_content}
    """
    data: Dict[str, str] = {}
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        print(f"⚠️  Không tìm thấy thư mục: {folder}", file=sys.stderr)
        return data

    excluded = {"urls.txt"}
    loaded, skipped = 0, 0

    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith(".txt"):
                continue
            if fn.lower() in excluded:
                skipped += 1
                continue

            path = os.path.join(root, fn)
            rel_name = os.path.relpath(path, folder)

            try:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        txt = f.read()
                except UnicodeDecodeError:
                    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                        txt = f.read()
                if txt:
                    data[rel_name] = txt
                    loaded += 1
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1
                print(f"⚠️  Lỗi đọc file {rel_name}: {e}", file=sys.stderr)

    print(f"📄 Loaded {loaded} .txt files (skipped {skipped}, excluded: {', '.join(sorted(excluded))}) from {folder}")
    return data

def main_All():
    os.makedirs(INDEX_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    process_documents(DOCS_DIR, DATA_DIR)
    process_documents(input_folder="./Documents/Accountant", output_folder="./src/app/Data/Data_All/Accountant")
    web_crawler("Data_All")
    processing_Data_doclinkToText(input_dir = "./Documents/HR/txt", output_dir = "./src/app/Data/Data_All/txt", 
                                input_txt_diagram = "./Documents/HR/Diagram/documents_workflowAndText", output_txt_diagram = "./src/app/Data/Data_All/Diagram/documents_workflowAndText",
                                input_dir_org_tree = "./Documents/HR/Diagram/procedure", output_dir_org_tree = "./src/app/Data/Data_All/Diagram/procedure")
    # processing_Data_dockinkToText_v2(input_dir="./Documents/Accountant", output_dir="./src/app/Data/Data_All/Accountant")
    raw = _load_text_files(DATA_DIR)
    if not raw:
        raise RuntimeError(f"Không có TXT/CSV trong {DATA_DIR}")
    docs: List[Document] = []
    for fname, text in raw.items():
        t = _clean_text(text)
        if not t:
            continue
        docs.append(Document(page_content=t, metadata={"source": fname, "page": -1}))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)
    for i, d in enumerate(chunks):
        d.metadata["chunk_id"] = i

    device = _select_device()
    batch = 64 if device=='cuda' and torch.cuda.mem_get_info()[0] > 8e9 else 16

    device = _select_device()
    model_kwargs = {"device": device}
    if os.environ.get("EMBED_QUANTIZE", "0") == "1":
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_NAME,
        model_kwargs=model_kwargs,
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
    )

    print(f"⚙️ Building FAISS… (chunks={len(chunks)}, size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}, device={device}, batch={batch})")
    vs = FAISS.from_documents(chunks, emb)
    vs.save_local(INDEX_DIR)
    print(f"✅ FAISS index saved at: {INDEX_DIR}")
