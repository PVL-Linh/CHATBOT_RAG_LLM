import os
from pathlib import Path
from typing import List
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from app.config.paths import FAISS_DIR_ACCOUNTANT, EMBED_MODEL_DIR
from app.rag_hr.utils_hr import select_device


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
        return 768

def _is_local_path(model_id: str) -> bool:
    p = Path(_to_str(model_id))
    if p.exists():
        return True
    s = _to_str(model_id)
    if s.startswith("ocal_"):
        return Path("l" + s).exists()
    return False

def _fix_typo_local(model_id: str) -> str:
    s = _to_str(model_id)
    return "l" + s if s.startswith("ocal_") else s

def _pick_model_id(dim: int) -> str:
    if EMBED_MODEL_DIR:
        return _to_str(EMBED_MODEL_DIR)

    for c in [
        "./src/app/models/local_multilingual_e5_large_instruct",
        "./src/app/models/local_multilingual_e5_large",
    ]:
        if Path(c).exists():
            return _to_str(c)

    by_dim = {
        384: "intfloat/multilingual-e5-small",
        768: "intfloat/multilingual-e5-base",
        1024: "intfloat/multilingual-e5-large",
    }
    return _to_str(by_dim.get(dim, "intfloat/multilingual-e5-large"))

class WithE5Prefixes:
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
    model_id = _fix_typo_local(model_id)
    model_id = _to_str(model_id)
    use_local = _is_local_path(model_id)
    model_kwargs = {"device": device}
    encode_kwargs = {
        "normalize_embeddings": True,
        "batch_size": 32 if device == "cuda" else 16,
    }

    if use_local:
        model_kwargs["local_files_only"] = True

    base = HuggingFaceEmbeddings(
        model_name=model_id,
        model_kwargs=model_kwargs,
        encode_kwargs=encode_kwargs,
    )

    if "instruct" in model_id.lower():
        return WithE5Prefixes(base, query_prefix="query: ", doc_prefix="passage: ")
    return base

def load_vectorstore():
    index_path = os.path.join(_to_str(FAISS_DIR_ACCOUNTANT), "index.faiss")
    if not os.path.isfile(index_path):
        raise RuntimeError(f"Không thấy FAISS index: {index_path}")

    dim = _read_index_dim(index_path)
    model_id = _pick_model_id(dim)
    device = select_device()
    emb = _build_embeddings(model_id, device)
    show = _to_str(Path(model_id).resolve()) if _is_local_path(model_id) else _to_str(model_id)
    print(f"🔤 Embedding model: {show} (index.d={dim}, device={device})")

    vs = FAISS.load_local(
        os.path.dirname(index_path),
        emb,
        allow_dangerous_deserialization=True
    )
    return vs

