import os
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from sympy import re

def LLM_model ():
    EMBED_MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "./src/models/local_e5_large_v2")
    FAISS_DIR = os.environ.get("FAISS_DIR", "./src/FAISS_Vector")
    LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://192.168.2.8:1234/v1/chat/completions")
    LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-3n-e4b-it-text")

    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL_DIR,
            encode_kwargs={"normalize_embeddings": True}
        )
        vector_store = FAISS.load_local(
            FAISS_DIR, embeddings, allow_dangerous_deserialization=True
        )
    except Exception as e:
        raise RuntimeError(f"Failed to init FAISS/embeddings: {e}")
    return embeddings, vector_store, LLM_ENDPOINT, LLM_MODEL