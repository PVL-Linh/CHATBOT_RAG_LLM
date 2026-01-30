# import os
# from langchain_community.vectorstores import FAISS
# from langchain_huggingface import HuggingFaceEmbeddings
# from .config_hr import INDEX_DIR_HR, EMBED_MODEL_NAME_HR
# from .utils_hr import select_device

# def load_vectorstore():
#     index_path = os.path.join(INDEX_DIR_HR, "index.faiss")
#     if not os.path.isfile(index_path):
#         raise RuntimeError(f"Không thấy FAISS index: {index_path}")

#     try:
#         import faiss
#         dim = int(faiss.read_index(index_path).d)
#     except Exception:
#         dim = 768

#     model_by_dim = {384: "intfloat/multilingual-e5-small",
#                     768: "intfloat/multilingual-e5-base",
#                     1024:"intfloat/multilingual-e5-large"}
#     model_id = EMBED_MODEL_NAME_HR or model_by_dim.get(dim) or "intfloat/multilingual-e5-base"

#     device = select_device()
#     emb = HuggingFaceEmbeddings(
#         model_name=model_id,
#         model_kwargs={"device": device},
#         encode_kwargs={"normalize_embeddings": True, "batch_size": 32 if device=="cuda" else 16},
#     )
#     print(f"🔤 Embedding model: {model_id} (index.d={dim})")
#     vs = FAISS.load_local(os.path.dirname(index_path), emb, allow_dangerous_deserialization=True)
#     return vs


# app/rag_hr/vectorstore_loader.py
# -*- coding: utf-8 -*-
import os
from pathlib import Path
from typing import List

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.config.paths import FAISS_DIR_HR, EMBED_MODEL_DIR
from .utils_hr import select_device


# ---------------- helpers ----------------
def _to_str(x) -> str:
    """Ép mọi kiểu (Path, WindowsPath, PosixPath, None) về str an toàn."""
    if isinstance(x, Path):
        return x.as_posix()
    return "" if x is None else str(x)

def _read_index_dim(index_path: str) -> int:
    try:
        import faiss
        return int(faiss.read_index(index_path).d)
    except Exception:
        return 768  # fallback phổ biến cho e5-base

def _is_local_path(model_id: str) -> bool:
    p = Path(_to_str(model_id))
    if p.exists():
        return True
    s = _to_str(model_id)
    if s.startswith("ocal_"):  # user gõ thiếu chữ 'l'
        return Path("l" + s).exists()
    return False

def _fix_typo_local(model_id: str) -> str:
    s = _to_str(model_id)
    return "l" + s if s.startswith("ocal_") else s

def _pick_model_id(dim: int) -> str:
    """
    Ưu tiên:
      1) EMBED_MODEL_DIR (local path nếu có)
      2) Local default nếu tồn tại
      3) Map theo index.d
    """
    # 1) Từ config.paths (có thể là Path) -> ép str
    if EMBED_MODEL_DIR:
        return _to_str(EMBED_MODEL_DIR)

    # 2) local default
    for c in [
        "./src/app/models/local_multilingual_e5_large_instruct",
        "./src/app/models/local_multilingual_e5_large",
    ]:
        if Path(c).exists():
            return _to_str(c)

    # 3) map theo dim
    by_dim = {
        384: "intfloat/multilingual-e5-small",
        768: "intfloat/multilingual-e5-base",
        1024: "intfloat/multilingual-e5-large",
    }
    return _to_str(by_dim.get(dim, "intfloat/multilingual-e5-base"))

class WithE5Prefixes:
    """Bọc thêm prefix cho E5-Instruct (query/passsage)."""
    def __init__(self, base_embed: HuggingFaceEmbeddings,
                 query_prefix: str = "query: ",
                 doc_prefix: str = "passage: "):
        self.base = base_embed
        self.query_prefix = query_prefix
        self.doc_prefix = doc_prefix

    def embed_documents(self, texts: List[str]):
        texts = [self.doc_prefix + (t or "") for t in texts]
        return self.base.embed_documents(texts)

    def embed_query(self, text: str):
        return self.base.embed_query(self.query_prefix + (text or ""))

def _build_embeddings(model_id: str, device: str):
    # 🔒 CHỐT: luôn là string thuần
    model_id = _fix_typo_local(model_id)
    model_id = _to_str(model_id)

    use_local = _is_local_path(model_id)

    model_kwargs = {"device": device}
    encode_kwargs = {
        "normalize_embeddings": True,
        "batch_size": 32 if device == "cuda" else 16,
    }

    # ép offline đúng nơi (SentenceTransformer)
    if use_local:
        model_kwargs["local_files_only"] = True

    # 👉 Pydantic yêu cầu str cho model_name
    base = HuggingFaceEmbeddings(
        model_name=model_id,
        model_kwargs=model_kwargs,
        encode_kwargs=encode_kwargs,
    )

    if "instruct" in model_id.lower():
        return WithE5Prefixes(base, query_prefix="query: ", doc_prefix="passage: ")
    return base

# ---------------- main loader ----------------
def load_vectorstore():
    index_path = os.path.join(_to_str(FAISS_DIR_HR), "index.faiss")
    if not os.path.isfile(index_path):
        raise RuntimeError(f"Không thấy FAISS index: {index_path}")

    dim = _read_index_dim(index_path)
    model_id = _pick_model_id(dim)
    device = select_device()
    emb = _build_embeddings(model_id, device)

    # Log gọn: nếu là path local, in absolute path
    show = _to_str(Path(model_id).resolve()) if _is_local_path(model_id) else _to_str(model_id)
    print(f"🔤 Embedding model: {show} (index.d={dim}, device={device})")

    vs = FAISS.load_local(
        os.path.dirname(index_path),
        emb,
        allow_dangerous_deserialization=True
    )
    return vs

