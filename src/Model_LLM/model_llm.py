# import os
# from langchain_community.vectorstores import FAISS
# from langchain_community.embeddings import HuggingFaceEmbeddings
# from sympy import re

# def LLM_model ():
#     EMBED_MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "./src/models/local_e5_large_v2")
#     FAISS_DIR = os.environ.get("FAISS_DIR", "./src/FAISS_Vector")
#     LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://192.168.2.8:1234/v1/chat/completions")
#     LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-3n-e4b-it-text")

#     try:
#         embeddings = HuggingFaceEmbeddings(
#             model_name=EMBED_MODEL_DIR,
#             encode_kwargs={"normalize_embeddings": True}
#         )
#         vector_store = FAISS.load_local(
#             FAISS_DIR, embeddings, allow_dangerous_deserialization=True
#         )
#     except Exception as e:
#         raise RuntimeError(f"Failed to init FAISS/embeddings: {e}")
#     return embeddings, vector_store, LLM_ENDPOINT, LLM_MODEL


# llm_bootstrap.py (hoặc nơi bạn đang để LLM_model)
# import os
# from langchain_community.vectorstores import FAISS
# from langchain_community.embeddings import HuggingFaceEmbeddings
# from .hybrid_retriever import build_hybrid_retriever  # NEW

# def LLM_model():
#     # EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_DIR", "intfloat/multilingual-e5-large")
#     EMBED_MODEL_NAME = "./src/models/local_multilingual_e5_large"
#     FAISS_DIR = os.environ.get("FAISS_DIR", "./src/FAISS_Vector")
#     LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://192.168.2.8:1234/v1/chat/completions")
#     LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-3n-e4b-it-text")

#     embeddings = HuggingFaceEmbeddings(
#         model_name=EMBED_MODEL_NAME,
#         encode_kwargs={"normalize_embeddings": True}
#     )
#     vector_store = FAISS.load_local(FAISS_DIR, embeddings, allow_dangerous_deserialization=True)

#     # Hybrid retriever (BM25 + FAISS with MMR)
#     retriever = build_hybrid_retriever(vector_store)

#     return embeddings, vector_store, retriever, LLM_ENDPOINT, LLM_MODEL


# llm_model_gemini.py
# llm_model_gemini.py

# ================== GEMINI =====================================
import os
from dotenv import load_dotenv

# Dùng bản mới để bỏ deprecation warning
try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ModuleNotFoundError:
    # fallback cho môi trường cũ
    from langchain_community.embeddings import HuggingFaceEmbeddings

from langchain_community.vectorstores import FAISS

from .hybrid_retriever import build_hybrid_retriever

# Gemini SDK
from google import genai as genai_new
from google.genai import types as genai_types

load_dotenv()

def _make_embeddings(model_name: str) -> HuggingFaceEmbeddings:
    """
    Tạo embeddings, ưu tiên theo ENV:
      - EMBED_DEVICE=cpu|cuda (nếu cung cấp)
      - EMBED_USE_GPU=1 (cho phép dùng CUDA nếu có)
    Tự fallback sang CPU nếu gặp CUDA OOM.
    """
    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        torch = None
        has_cuda = False

    force_device = (os.getenv("EMBED_DEVICE") or "").strip().lower()
    if force_device in ("cpu", "cuda"):
        device = force_device
    else:
        use_gpu = (os.getenv("EMBED_USE_GPU") or "0").strip() == "1"
        device = "cuda" if (use_gpu and has_cuda) else "cpu"

    batch = int(os.getenv("EMBED_BATCH", "16"))

    try:
        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},                 # ÉP device
            encode_kwargs={"normalize_embeddings": True, "batch_size": batch}
        )
    except Exception as e:
        # Nếu vấp CUDA OOM thì fallback về CPU
        msg = str(e)
        if "CUDA" in msg or "cuda" in msg or "out of memory" in msg:
            return HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8}
            )
        raise

def LLM_model():
    # ====== Embeddings + FAISS ======
    EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_DIR", "./src/models/local_multilingual_e5_large")
    FAISS_DIR = os.getenv("FAISS_DIR", "./src/FAISS_Vector")

    embeddings = _make_embeddings(EMBED_MODEL_NAME)
    vector_store = FAISS.load_local(FAISS_DIR, embeddings, allow_dangerous_deserialization=True)

    # Hybrid retriever (BM25 + FAISS with MMR)
    retriever = build_hybrid_retriever(vector_store)

    # ====== Gemini ======
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY trong .env")

    GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
    gclient = genai_new.Client(api_key=GEMINI_API_KEY)

    GEN_CFG = genai_types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "6000")),
        top_p=0.95,
        top_k=40,
    )

    # Trả về giống chữ ký bạn đang dùng ở chat_api
    return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG




# llm_bootstrap.py
# llm_bootstrap.py
# import os
# from typing import Tuple

# from langchain_community.vectorstores import FAISS
# from langchain_huggingface import HuggingFaceEmbeddings  # ✅ dùng package mới

# # Import hybrid retriever và hàm normalize_query
# from .hybrid_retriever import build_hybrid_retriever, normalize_query


# def _select_device() -> str:
#     """Chọn 'cuda' nếu có GPU, ngược lại 'cpu'."""
#     try:
#         import torch
#         return "cuda" if torch.cuda.is_available() else "cpu"
#     except Exception:
#         return "cpu"


# class NormalizedRetriever:
#     """
#     Wrapper cho retriever để luôn chuẩn hoá câu hỏi người dùng
#     theo CASE_NORM (lower/upper) đã cấu hình trong hybrid_retriever.py.
#     """
#     def __init__(self, base_retriever):
#         self._base = base_retriever

#     def get_relevant_documents(self, query: str):
#         q = normalize_query(query)
#         return self._base.get_relevant_documents(q)

#     # Nếu bạn có dùng API async ở đâu đó, mở comment dưới:
#     # async def aget_relevant_documents(self, query: str):
#     #     q = normalize_query(query)
#     #     return await self._base.aget_relevant_documents(q)


# def LLM_model() -> Tuple[HuggingFaceEmbeddings, FAISS, NormalizedRetriever, str, str]:
#     """
#     Trả về:
#         embeddings, vector_store, retriever(đã normalize query), LLM_ENDPOINT, LLM_MODEL
#     """
#     # ==== Config ====
#     EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_DIR", "./src/models/local_multilingual_e5_large")
#     FAISS_DIR = os.environ.get("FAISS_DIR", "./src/FAISS_Vector")

#     # Endpoint/model LLM (LM Studio / OpenAI compatible)
#     LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://192.168.1.38:1234/v1/chat/completions")
#     LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-3n-e4b-it-text")

#     # ==== Embeddings & VectorStore ====
#     device = _select_device()
#     batch = int(os.environ.get("EMB_BATCH", 32 if device == "cuda" else 8))

#     embeddings = HuggingFaceEmbeddings(
#         model_name=EMBED_MODEL_NAME,
#         model_kwargs={"device": device},                         # ✅ chỉ truyền device
#         encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
#     )

#     vector_store = FAISS.load_local(
#         FAISS_DIR,
#         embeddings,
#         allow_dangerous_deserialization=True
#     )

#     # ==== Hybrid retriever (BM25 + FAISS with MMR) ====
#     base_retriever = build_hybrid_retriever(vector_store)

#     # Bọc retriever để tự normalize query (lower/upper tuỳ CASE_NORM)
#     retriever = NormalizedRetriever(base_retriever)

#     return embeddings, vector_store, retriever, LLM_ENDPOINT, LLM_MODEL
