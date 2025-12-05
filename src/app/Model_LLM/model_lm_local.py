import os
from typing import Optional, Tuple
# --- LangChain Embeddings (ưu tiên lib mới, fallback lib cũ) ---
try:
    from langchain_huggingface import HuggingFaceEmbeddings 
except Exception:
    from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
try:
    from app.Model_LLM.hybrid_retriever import build_hybrid_retriever
except Exception:
    build_hybrid_retriever = None

# Gemini SDK (google-genai)
# pip install google-genai
from google import genai as genai_new
from google.genai import types as genai_types

# HF Hub auto-download
# pip install --upgrade huggingface_hub
from huggingface_hub import snapshot_download


# =========================
# Helpers
# =========================
def _abs(p: str) -> str:
    """Chuyển path tương đối -> tuyệt đối dựa trên REPO_ROOT (hữu ích trong Docker)."""
    base = os.getenv("REPO_ROOT", "")
    if not base:
        base = os.getcwd()  # fallback an toàn
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p.lstrip("./")))


def _ensure_exists(path: str, what: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{what} không tồn tại: {path}")


def ensure_local_hf_model(local_dir: str, model_id: str, revision: Optional[str] = None) -> str:
    """
    Đảm bảo thư mục local_dir chứa model từ Hugging Face.
    Nếu thiếu -> tự động tải bằng snapshot_download (copy thực, không symlink).
    - model_id: ví dụ "intfloat/multilingual-e5-large"
    - revision: tag/commit cụ thể (tuỳ chọn)
    ENV hỗ trợ:
      - HF_TOKEN: nếu repo private
    """
    local_dir = _abs(local_dir)
    os.makedirs(local_dir, exist_ok=True)

    # Kiểm tra đã có model đầy đủ?
    # Điều kiện: có config.json và (pytorch_model.bin hoặc model.safetensors)
    has_config = os.path.exists(os.path.join(local_dir, "config.json"))
    has_weights = any(
        os.path.exists(os.path.join(local_dir, fname))
        for fname in ("pytorch_model.bin", "model.safetensors")
    )
    if has_config and has_weights:
        return local_dir  # đã sẵn sàng

    token = os.getenv("HF_TOKEN") or None
    try:
        print(f"[model_llm] Tải model '{model_id}' về: {local_dir} (revision={revision or 'default'})")
        snapshot_download(
            repo_id=model_id,
            revision=revision,
            local_dir=local_dir,
            local_dir_use_symlinks=False,  # copy file thật → dễ đóng gói Docker
            resume_download=True,
            token=token,
        )
    except Exception as e:
        raise RuntimeError(
            f"Không tải được model {model_id} về {local_dir}. "
            f"Kiểm tra mạng/HF_TOKEN (nếu repo private). Chi tiết: {e}"
        )

    # Kiểm tra lại sau khi tải
    has_config = os.path.exists(os.path.join(local_dir, "config.json"))
    has_weights = any(
        os.path.exists(os.path.join(local_dir, fname))
        for fname in ("pytorch_model.bin", "model.safetensors")
    )
    if not (has_config and has_weights):
        raise RuntimeError(
            f"Model {model_id} tải chưa đủ file cần thiết trong {local_dir}."
        )

    return local_dir


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
        torch = None  # noqa
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
            model_name=model_path_or_name,  # có thể là tên HF hoặc đường dẫn local
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
        )
    except Exception as e:
        # Nếu vấp CUDA OOM/driver → fallback CPU
        msg = str(e).lower()
        if any(k in msg for k in ("cuda", "out of memory", "cublas", "cudnn")):
            return HuggingFaceEmbeddings(
                model_name=model_path_or_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
            )
        raise


def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY (hoặc GOOGLE_API_KEY) trong biến môi trường.")
    return genai_new.Client(api_key=api_key)


# =========================
# Factory chính
# =========================
def LLM_model() -> Tuple[
    HuggingFaceEmbeddings,
    FAISS,
    object,
    genai_new.Client,
    str,
    genai_types.GenerateContentConfig,
]:
    """
    Trả về:
      embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
    ENV liên quan:
      - EMBED_MODEL_ID        (mặc định: intfloat/multilingual-e5-large)
      - EMBED_REVISION        (tuỳ chọn)
      - EMBED_MODEL_PATH      (mặc định: ./src/app/models/local_multilingual_e5_large)
      - EMBED_DEVICE          (cpu|cuda) hoặc EMBED_USE_GPU=1
      - EMBED_BATCH           (mặc định 16)
      - GEMINI_API_KEY / GOOGLE_API_KEY
      - GEMINI_TEXT_MODEL     (mặc định: gemini-2.0-flash)
      - GEMINI_TEMPERATURE    (0.2)
      - GEMINI_MAX_OUTPUT     (6000)
      - GEMINI_TOP_P          (0.95)
      - GEMINI_TOP_K          (40)
    """
    # ====== Embeddings + FAISS ======
    EMBED_MODEL_ID = os.getenv("EMBED_MODEL_ID", "intfloat/multilingual-e5-large")
    EMBED_REVISION = os.getenv("EMBED_REVISION")  # ví dụ: "main" hoặc commit cụ thể
    EMBED_MODEL_PATH = os.getenv(
        "EMBED_MODEL_PATH",
        "./src/app/models/local_multilingual_e5_large",
    )
    FAISS_DIR = _abs("./src/app/vectorstore/FAISS_Vector_All")

    # Auto-download nếu thiếu
    EMBED_MODEL_PATH = ensure_local_hf_model(
        local_dir=EMBED_MODEL_PATH,
        model_id=EMBED_MODEL_ID,
        revision=EMBED_REVISION,
    )

    embeddings = _make_embeddings(EMBED_MODEL_PATH)

    if not os.path.isdir(FAISS_DIR):
        raise FileNotFoundError(
            f"FAISS directory không tồn tại: {FAISS_DIR}. "
            f"Hãy build trước vector store (ingest) hoặc mount đúng thư mục."
        )

    vector_store = FAISS.load_local(
        FAISS_DIR,
        embeddings,
        allow_dangerous_deserialization=True,
    )

    # Hybrid retriever (BM25 + FAISS + MMR) nếu module có sẵn
    if callable(build_hybrid_retriever):
        retriever = build_hybrid_retriever(vector_store)
    else:
        # Fallback: retriever mặc định MMR
        # k=6/8 tuỳ dữ liệu; bạn có thể tinh chỉnh thêm search_kwargs
        retriever = vector_store.as_retriever(search_type="mmr", search_kwargs={"k": 6})

    # ====== Gemini ======
    gclient = get_gemini_client()
    GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")

    GEN_CFG = genai_types.GenerateContentConfig(
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "6000")),
        top_p=float(os.getenv("GEMINI_TOP_P", "0.95")),
        top_k=int(os.getenv("GEMINI_TOP_K", "40")),
    )

    return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG





# import os
# from dotenv import load_dotenv
# from langchain_community.embeddings import HuggingFaceEmbeddings
# from langchain_community.vectorstores import FAISS
# from app.Model_LLM.hybrid_retriever import build_hybrid_retriever

# # Gemini SDK
# from google import genai as genai_new
# from google.genai import types as genai_types

# load_dotenv()

# # ---- Helpers ----
# def _abs(p: str) -> str:
#     """Chuyển path tương đối -> tuyệt đối dựa trên repo root (chạy tốt trong Docker)."""
#     # file này nằm ở đâu không quan trọng, miễn PYTHONPATH=/app khi chạy Docker
#     base = os.getenv("REPO_ROOT", "")
#     return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p.lstrip("./")))

# def _ensure_exists(path: str, what: str):
#     if not os.path.exists(path):
#         raise FileNotFoundError(f"{what} không tồn tại: {path}")

# # ---- Embeddings ----
# def _make_embeddings(model_path_or_name: str) -> HuggingFaceEmbeddings:
#     """
#     Tạo embeddings, ưu tiên theo ENV:
#       - EMBED_DEVICE=cpu|cuda
#       - EMBED_USE_GPU=1 (nếu có CUDA)
#       - EMBED_BATCH (mặc định 16)
#     Fallback sang CPU nếu gặp CUDA OOM.
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
#             model_name=model_path_or_name,                    # có thể là tên HF hoặc đường dẫn local
#             model_kwargs={"device": device},
#             encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
#         )
#     except Exception as e:
#         # Nếu vấp CUDA OOM thì fallback về CPU
#         msg = str(e)
#         if any(k in msg.lower() for k in ("cuda", "out of memory", "cublas", "cudnn")):
#             return HuggingFaceEmbeddings(
#                 model_name=model_path_or_name,
#                 model_kwargs={"device": "cpu"},
#                 encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
#             )
#         raise



# def get_gemini_client():
#     api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
#     if not api_key:
#         raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) in environment")
#     return genai_new.Client(api_key=api_key)



# # ---- Factory chính cho LLM + RAG ----
# def LLM_model():
#     """
#     Trả về:
#       embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
#     """
#     # ====== Embeddings + FAISS ======
#     # Chuẩn hoá tên biến ENV và đường dẫn mặc định theo cấu trúc mới.
#     EMBED_MODEL_PATH = os.getenv(
#         "EMBED_MODEL_PATH",  # đặt theo tên rõ ràng hơn
#         "./src/app/models/local_multilingual_e5_large",
#     )
#     FAISS_DIR = "./src/app/vectorstore/FAISS_Vector"

#     _ensure_exists(EMBED_MODEL_PATH, "EMBED_MODEL_PATH")

#     embeddings = _make_embeddings(EMBED_MODEL_PATH)

#     vector_store = FAISS.load_local(
#         FAISS_DIR,
#         embeddings,
#         allow_dangerous_deserialization=True
#     )

#     # Hybrid retriever (BM25 + FAISS with MMR) – theo module của bạn
#     retriever = build_hybrid_retriever(vector_store)

#     # ====== Gemini ======
#     GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
#     if not GEMINI_API_KEY:
#         raise RuntimeError("Thiếu GEMINI_API_KEY trong .env")

#     GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
#     gclient = genai_new.Client(api_key=GEMINI_API_KEY)

#     GEN_CFG = genai_types.GenerateContentConfig(
#         temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
#         max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "6000")),
#         top_p=float(os.getenv("GEMINI_TOP_P", "0.95")),
#         top_k=int(os.getenv("GEMINI_TOP_K", "40")),
#     )

#     return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
