# import os
# from dotenv import load_dotenv

# # Dùng bản mới để bỏ deprecation warning
# from langchain_community.embeddings import HuggingFaceEmbeddings
# from langchain_community.vectorstores import FAISS

# from app.Model_LLM.hybrid_retriever import build_hybrid_retriever

# # Gemini SDK
# from google import genai as genai_new
# from google.genai import types as genai_types

# load_dotenv()

# def _make_embeddings(model_name: str) -> HuggingFaceEmbeddings:
#     """
#     Tạo embeddings, ưu tiên theo ENV:
#       - EMBED_DEVICE=cpu|cuda (nếu cung cấp)
#       - EMBED_USE_GPU=1 (cho phép dùng CUDA nếu có)
#     Tự fallback sang CPU nếu gặp CUDA OOM.
#     """
#     try:
#         import torch
#         has_cuda = torch.cuda.is_available()
#     except Exception:
#         torch = None
#         has_cuda = False

#     force_device = (os.getenv("EMBED_DEVICE") or "").strip().lower()
#     if force_device in ("cpu", "cuda"):
#         device = force_device
#     else:
#         use_gpu = (os.getenv("EMBED_USE_GPU") or "0").strip() == "1"
#         device = "cuda" if (use_gpu and has_cuda) else "cpu"

#     batch = int(os.getenv("EMBED_BATCH", "16"))

#     try:
#         return HuggingFaceEmbeddings(
#             model_name=model_name,
#             model_kwargs={"device": device},                 # ÉP device
#             encode_kwargs={"normalize_embeddings": True, "batch_size": batch}
#         )
#     except Exception as e:
#         # Nếu vấp CUDA OOM thì fallback về CPU
#         msg = str(e)
#         if "CUDA" in msg or "cuda" in msg or "out of memory" in msg:
#             return HuggingFaceEmbeddings(
#                 model_name=model_name,
#                 model_kwargs={"device": "cpu"},
#                 encode_kwargs={"normalize_embeddings": True, "batch_size": 8}
#             )
#         raise

# def LLM_model():
#     # ====== Embeddings + FAISS ======
#     # EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_DIR", "./src/app/models/local_multilingual_e5_large")
#     # FAISS_DIR = os.getenv("FAISS_DIR", "./src/app/vectorstore/FAISS_Vector")
#     EMBED_MODEL_NAME = os.getenv(
#         "EMBED_MODEL_NAME",
#         "./src/app/models/local_multilingual_e5_large"
#     )

#     # Đường dẫn FAISS index (mặc định thư mục faiss_index đã chuẩn hóa)
#     FAISS_DIR = os.getenv(
#         "FAISS_DIR",
#         "./src/app/vectorstore/faiss_index"
# )

#     embeddings = _make_embeddings(EMBED_MODEL_NAME)
#     vector_store = FAISS.load_local(FAISS_DIR, embeddings, allow_dangerous_deserialization=True)

#     # Hybrid retriever (BM25 + FAISS with MMR)
#     retriever = build_hybrid_retriever(vector_store)

#     # ====== Gemini ======
#     GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
#     if not GEMINI_API_KEY:
#         raise RuntimeError("Thiếu GEMINI_API_KEY trong .env")

#     GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
#     gclient = genai_new.Client(api_key=GEMINI_API_KEY)

#     GEN_CFG = genai_types.GenerateContentConfig(
#         temperature=0.2,
#         max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "6000")),
#         top_p=0.95,
#         top_k=40,
#     )

#     # Trả về giống chữ ký bạn đang dùng ở chat_api
#     return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
import os
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from app.Model_LLM.hybrid_retriever import build_hybrid_retriever

# Gemini SDK
from google import genai as genai_new
from google.genai import types as genai_types

load_dotenv()

# ---- Helpers ----
def _abs(p: str) -> str:
    """Chuyển path tương đối -> tuyệt đối dựa trên repo root (chạy tốt trong Docker)."""
    # file này nằm ở đâu không quan trọng, miễn PYTHONPATH=/app khi chạy Docker
    base = os.getenv("REPO_ROOT", "")
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p.lstrip("./")))

def _ensure_exists(path: str, what: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{what} không tồn tại: {path}")

# ---- Embeddings ----
def _make_embeddings(model_path_or_name: str) -> HuggingFaceEmbeddings:
    """
    Tạo embeddings, ưu tiên theo ENV:
      - EMBED_DEVICE=cpu|cuda
      - EMBED_USE_GPU=1 (nếu có CUDA)
      - EMBED_BATCH (mặc định 16)
    Fallback sang CPU nếu gặp CUDA OOM.
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
            model_name=model_path_or_name,                    # có thể là tên HF hoặc đường dẫn local
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
        )
    except Exception as e:
        # Nếu vấp CUDA OOM thì fallback về CPU
        msg = str(e)
        if any(k in msg.lower() for k in ("cuda", "out of memory", "cublas", "cudnn")):
            return HuggingFaceEmbeddings(
                model_name=model_path_or_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
            )
        raise



def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) in environment")
    return genai_new.Client(api_key=api_key)



# ---- Factory chính cho LLM + RAG ----
def LLM_model():
    """
    Trả về:
      embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
    """
    # ====== Embeddings + FAISS ======
    # Chuẩn hoá tên biến ENV và đường dẫn mặc định theo cấu trúc mới.
    EMBED_MODEL_PATH = os.getenv(
        "EMBED_MODEL_PATH",  # đặt theo tên rõ ràng hơn
        "./src/app/models/local_multilingual_e5_large",
    )
    FAISS_DIR = "./src/app/vectorstore/FAISS_Vector"

    _ensure_exists(EMBED_MODEL_PATH, "EMBED_MODEL_PATH")

    embeddings = _make_embeddings(EMBED_MODEL_PATH)

    vector_store = FAISS.load_local(
        FAISS_DIR,
        embeddings,
        allow_dangerous_deserialization=True
    )

    # Hybrid retriever (BM25 + FAISS with MMR) – theo module của bạn
    retriever = build_hybrid_retriever(vector_store)

    # ====== Gemini ======
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu GEMINI_API_KEY trong .env")

    GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
    gclient = genai_new.Client(api_key=GEMINI_API_KEY)

    GEN_CFG = genai_types.GenerateContentConfig(
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "6000")),
        top_p=float(os.getenv("GEMINI_TOP_P", "0.95")),
        top_k=int(os.getenv("GEMINI_TOP_K", "40")),
    )

    return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
