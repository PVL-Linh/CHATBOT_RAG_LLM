import os
import faiss  # type: ignore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from .config_hr import INDEX_DIR, EMBED_MODEL_NAME
from .utils_hr import select_device

def load_faiss_vs():
    index_path = os.path.join(INDEX_DIR, "index.faiss")
    if not os.path.isfile(index_path):
        raise RuntimeError(
            f"Không tìm thấy FAISS index: {index_path}\n→ Kiểm tra INDEX_DIR hoặc build index trước."
        )
    try:
        idx = faiss.read_index(index_path)
        dim = int(idx.d)
    except Exception as e:
        raise RuntimeError(f"Không đọc được index.faiss tại {index_path}: {e}")

    model_by_dim = {384: "intfloat/multilingual-e5-small", 768: "intfloat/multilingual-e5-base", 1024: "intfloat/multilingual-e5-large"}
    model_id = EMBED_MODEL_NAME or model_by_dim.get(dim)
    if not model_id:
        raise RuntimeError(
            f"Không suy ra model embedding cho dim={dim}. Set EMBED_MODEL_NAME trong .env hoặc dùng 1 trong {model_by_dim}"
        )

    print(f"🔤 Embedding model: {model_id} (index.d={dim})")

    device = select_device()
    emb = HuggingFaceEmbeddings(
        model_name=model_id,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 32 if device == "cuda" else 16},
    )

    try:
        vs = FAISS.load_local(INDEX_DIR, emb, allow_dangerous_deserialization=True)
    except Exception as e:
        raise RuntimeError(
            f"FAISS.load_local thất bại tại {INDEX_DIR}. Kiểm tra index.faiss/index.pkl. Chi tiết: {e}"
        )
    return vs
