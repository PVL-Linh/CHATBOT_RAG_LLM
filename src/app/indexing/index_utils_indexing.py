# app/indexing/index_utils_indexing.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Tuple

from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

# ===== Config cơ bản (bạn có thể lấy từ env tuỳ ý) =====
EMBED_MODEL_NAME = os.environ.get(
    "EMBED_MODEL_DIR",  # giữ tên biến cũ của bạn nếu đang dùng
    "intfloat/multilingual-e5-large"
)

def _select_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def build_embeddings() -> Tuple[HuggingFaceEmbeddings, str, int]:
    """
    Trả về đúng 3 giá trị: (emb, device, batch).
    """
    device = _select_device()
    batch = 32 if device == "cuda" else 8
    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_NAME,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
    )
    return emb, device, batch

def faiss_exists(index_dir: str) -> bool:
    """
    Kiểm tra FAISS có tồn tại không (theo cấu trúc LangChain: index.faiss + index.pkl)
    """
    p = Path(index_dir)
    return (p / "index.faiss").exists() and (p / "index.pkl").exists()

def load_faiss(index_dir: str, emb: HuggingFaceEmbeddings | None = None) -> FAISS:
    """
    Hỗ trợ tham số 'emb' tuỳ chọn (tương thích các chỗ gọi cũ như load_faiss(index_dir, emb=None)).
    Nếu emb=None, tự build_embeddings().
    """
    if emb is None:
        emb, _device, _batch = build_embeddings()
    return FAISS.load_local(index_dir, emb, allow_dangerous_deserialization=True)

def save_faiss(index_dir: str, vs: FAISS) -> None:
    """
    Lưu FAISS theo cấu trúc LangChain.
    """
    vs.save_local(index_dir)
