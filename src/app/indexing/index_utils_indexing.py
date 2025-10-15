# src/app/indexing/index_utils_indexing.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Union
from langchain_community.vectorstores import FAISS

PathLike = Union[str, os.PathLike]
INDEX_FILES = ("index.faiss", "index.pkl")


def faiss_exists(index_dir: PathLike) -> bool:
    d = Path(index_dir)
    return all((d / name).exists() for name in INDEX_FILES)


def load_faiss(index_dir: PathLike, emb) -> FAISS:
    d = str(index_dir)
    if not faiss_exists(d):
        raise RuntimeError(f"Index not initialized at: {d}")
    return FAISS.load_local(d, emb, allow_dangerous_deserialization=True)


def save_faiss(vs: FAISS, index_dir: PathLike) -> None:
    d = str(index_dir)
    os.makedirs(d, exist_ok=True)
    vs.save_local(d)
