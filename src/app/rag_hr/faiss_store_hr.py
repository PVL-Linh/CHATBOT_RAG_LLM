# -*- coding: utf-8 -*-
import os
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from .config_hr import INDEX_DIR_HR, EMBED_MODEL_NAME_HR
from .utils_hr import select_device

def load_vectorstore():
    index_path = os.path.join(INDEX_DIR_HR, "index.faiss")
    if not os.path.isfile(index_path):
        raise RuntimeError(f"Không thấy FAISS index: {index_path}")

    try:
        import faiss
        dim = int(faiss.read_index(index_path).d)
    except Exception:
        dim = 768

    model_by_dim = {384: "intfloat/multilingual-e5-small",
                    768: "intfloat/multilingual-e5-base",
                    1024:"intfloat/multilingual-e5-large"}
    model_id = EMBED_MODEL_NAME_HR or model_by_dim.get(dim) or "intfloat/multilingual-e5-base"

    device = select_device()
    emb = HuggingFaceEmbeddings(
        model_name=model_id,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 32 if device=="cuda" else 16},
    )
    print(f"🔤 Embedding model: {model_id} (index.d={dim})")
    vs = FAISS.load_local(os.path.dirname(index_path), emb, allow_dangerous_deserialization=True)
    return vs
