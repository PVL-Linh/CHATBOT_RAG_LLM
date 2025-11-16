# app/indexing/index_utils_indexing.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Tuple
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

EMBED_MODEL_NAME = os.environ.get(
    "EMBED_MODEL_DIR",
    "intfloat/multilingual-e5-large"
)

def _select_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def build_embeddings() -> Tuple[HuggingFaceEmbeddings, str, int]:
    device = _select_device()
    batch = 32 if device == "cuda" else 8
    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_NAME,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
    )
    return emb, device, batch

def faiss_exists(index_dir: str) -> bool:
    p = Path(index_dir)
    return (p / "index.faiss").exists() and (p / "index.pkl").exists()

def load_faiss(index_dir: str, emb: HuggingFaceEmbeddings | None = None) -> FAISS:
    if emb is None:
        emb, _device, _batch = build_embeddings()
    return FAISS.load_local(index_dir, emb, allow_dangerous_deserialization=True)

def save_faiss(index_dir: str, vs: FAISS) -> None:
    vs.save_local(index_dir)
