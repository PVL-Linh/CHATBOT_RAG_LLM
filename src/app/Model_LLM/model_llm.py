import os
import errno
from typing import Optional, Tuple

from dotenv import load_dotenv
load_dotenv()

# --- Optional: Ẩn warnings deprecate từ huggingface_hub ---
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="huggingface_hub.file_download")
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub.file_download")

# --- LangChain Embeddings (ưu tiên lib mới, fallback lib cũ) ---
try:
    # pip install -U langchain-huggingface
    from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore
except Exception:
    # pip install langchain-community
    from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore

from langchain_core.embeddings import Embeddings as LCEmbeddings  # type: ignore
from langchain_community.vectorstores import FAISS

# Hybrid retriever (nếu có)
try:
    from app.Model_LLM.hybrid_retriever import build_hybrid_retriever  # type: ignore
except Exception:
    build_hybrid_retriever = None  # fallback phía dưới

# Gemini SDK (google-genai) — pip install google-genai
from google import genai as genai_new
from google.genai import types as genai_types

# HF Hub — pip install --upgrade huggingface_hub
from huggingface_hub import snapshot_download


# =========================
# Helpers
# =========================
def _abs(p: str) -> str:
    """Chuyển path tương đối -> tuyệt đối dựa trên REPO_ROOT (hữu ích trong Docker/Spaces)."""
    base = os.getenv("REPO_ROOT", "")
    if not base:
        base = os.getcwd()  # fallback an toàn
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p.lstrip("./")))


def _ensure_exists(path: str, what: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{what} không tồn tại: {path}")


def _is_disk_full_error(exc: Exception) -> bool:
    s = str(exc).lower()
    eno = getattr(exc, "errno", None)
    return (
        isinstance(exc, OSError) and eno == errno.ENOSPC
        or "no space left" in s
        or "disk full" in s
        or "insufficient space" in s
        or "no enough space" in s
    )


def ensure_local_hf_model(local_dir: str, model_id: str, revision: Optional[str] = None) -> str:
    """
    GIỮ LẠI cho môi trường không phải Spaces.
    Trên Hugging Face Spaces, ta **không gọi** hàm này (ép remote).
    """
    local_dir = _abs(local_dir)
    os.makedirs(local_dir, exist_ok=True)

    has_config = os.path.exists(os.path.join(local_dir, "config.json"))
    has_weights = any(
        os.path.exists(os.path.join(local_dir, fname))
        for fname in ("pytorch_model.bin", "model.safetensors")
    )
    if has_config and has_weights:
        return local_dir

    token = os.getenv("HF_TOKEN") or None
    force = (os.getenv("HF_FORCE_DOWNLOAD", "0") == "1")

    try:
        print(f"[model_llm] Tải model '{model_id}' về: {local_dir} (revision={revision or 'default'})")
        snapshot_download(
            repo_id=model_id,
            revision=revision,
            local_dir=local_dir,
            token=token,
            force_download=force,
            allow_patterns=[
                "config.json",
                "pytorch_model.bin",
                "*.safetensors",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "sentencepiece.*",
                "spiece.*",
                "vocab.*",
            ],
        )
    except Exception as e:
        raise RuntimeError(
            f"Không tải được model {model_id} về {local_dir}. "
            f"Kiểm tra mạng/HF_TOKEN (nếu repo private). Chi tiết: {e}"
        )

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


def _make_embeddings_local(model_path_or_name: str) -> LCEmbeddings:
    """Embeddings LOCAL: ưu tiên GPU nếu có, fallback CPU."""
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
            model_name=model_path_or_name,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
        )
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("cuda", "out of memory", "cublas", "cudnn")):
            return HuggingFaceEmbeddings(
                model_name=model_path_or_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
            )
        raise


def _make_embeddings_remote(model_id: str) -> LCEmbeddings:
    """
    Embeddings REMOTE trên Hugging Face Inference.
    Env cần:
      - HUGGINGFACEHUB_API_TOKEN (ưu tiên) hoặc HF_TOKEN
    """
    api_key = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")
    if not api_key:
        raise RuntimeError("Thiếu HUGGINGFACEHUB_API_TOKEN/HF_TOKEN để dùng Hugging Face Inference.")

    try:
        from langchain_huggingface import HuggingFaceEndpointEmbeddings  # type: ignore
        return HuggingFaceEndpointEmbeddings(
            model=model_id,
            task="feature-extraction",
            huggingfacehub_api_token=api_key,
        )
    except Exception:
        from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings  # type: ignore
        return HuggingFaceInferenceAPIEmbeddings(
            api_key=api_key,
            model_name=model_id,
        )


def _maybe_download_faiss_from_hub(default_dir: str) -> str:
    """
    Nếu FAISS_DIR chưa tồn tại và có cấu hình repo HF, tải index từ Hub về **runtime**.
    Trả về đường dẫn cuối cùng dùng để FAISS.load_local().
    ENV:
      - FAISS_HUB_REPO (vd: username/my-faiss-index)  [bắt buộc để tải]
      - FAISS_HUB_REPO_TYPE = dataset|model (mặc định: dataset)
      - FAISS_HUB_SUBDIR (vd: vectorstore/FAISS_Vector) (mặc định: "vectorstore/FAISS_Vector")
      - FAISS_LOCAL_DIR (override đường dẫn local nếu muốn)
    """
    local_dir = os.getenv("FAISS_LOCAL_DIR") or default_dir
    local_dir = _abs(local_dir)

    if os.path.isdir(local_dir):
        return local_dir

    repo_id = os.getenv("FAISS_HUB_REPO")
    if not repo_id:
        # Không có repo để tải → giữ nguyên local_dir (FAISS sẽ báo lỗi ở dưới nếu thiếu)
        return local_dir

    repo_type = os.getenv("FAISS_HUB_REPO_TYPE", "dataset")
    subdir = os.getenv("FAISS_HUB_SUBDIR", "vectorstore/FAISS_Vector_All").strip().strip("/")

    print(f"[model_llm] Tải FAISS index từ Hub: {repo_type}:{repo_id}/{subdir}")
    snap_path = snapshot_download(
        repo_id=repo_id,
        repo_type=repo_type,
        allow_patterns=[f"{subdir}/*", f"{subdir}/**/*", "*.faiss", "*.pkl", "*.json"],
    )
    faiss_load_dir = os.path.join(snap_path, subdir)
    return faiss_load_dir


def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY (hoặc GOOGLE_API_KEY) trong biến môi trường.")
    return genai_new.Client(api_key=api_key)


# =========================
# Factory chính
# =========================
def LLM_model() -> Tuple[
    LCEmbeddings,          # embeddings (local hoặc remote)
    FAISS,                 # vector_store
    object,                # retriever
    genai_new.Client,      # gclient
    str,                   # GEMINI_MODEL
    genai_types.GenerateContentConfig,  # GEN_CFG
]:
    """
    Trả về:
      embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
    ENV liên quan:
      - EMBED_MODEL_ID        (mặc định: intfloat/multilingual-e5-large)
      - EMBED_REVISION        (tuỳ chọn, chỉ dùng nếu chạy local)
      - EMBED_MODEL_PATH      (mặc định: ./src/app/models/local_multilingual_e5_large) (chỉ dùng nếu local)
      - EMBED_FORCE_REMOTE    (1|0|auto) — auto: nếu phát hiện SPACE_ID → remote
      - HUGGINGFACEHUB_API_TOKEN hoặc HF_TOKEN (cho remote)
      - FAISS_DIR / FAISS_LOCAL_DIR (tuỳ chọn)
      - FAISS_HUB_REPO / FAISS_HUB_REPO_TYPE / FAISS_HUB_SUBDIR (tuỳ chọn)
      - GEMINI_*
    """
    EMBED_MODEL_ID = os.getenv("EMBED_MODEL_ID", "intfloat/multilingual-e5-large")
    EMBED_REVISION = os.getenv("EMBED_REVISION")  # chỉ dùng khi local
    EMBED_MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "./src/app/models/local_multilingual_e5_large")

    # ——— Chế độ remote mặc định trên Spaces
    force_remote_env = (os.getenv("EMBED_FORCE_REMOTE", "auto").strip().lower())
    running_on_spaces = bool(os.getenv("SPACE_ID"))  # Hugging Face Spaces đặt biến này
    if force_remote_env in ("1", "true", "yes"):
        use_remote = True
    elif force_remote_env == "auto":
        use_remote = running_on_spaces  # auto → nếu là Spaces thì remote
    else:
        use_remote = False

    # ====== Embeddings ======
    if use_remote:
        print("[model_llm] Dùng Remote Embeddings (Hugging Face Inference).")
        embeddings: LCEmbeddings = _make_embeddings_remote(EMBED_MODEL_ID)
    else:
        # Chỉ dùng cho môi trường không phải Spaces (hoặc khi bạn ép local)
        try:
            EMBED_MODEL_PATH = ensure_local_hf_model(
                local_dir=EMBED_MODEL_PATH,
                model_id=EMBED_MODEL_ID,
                revision=EMBED_REVISION,
            )
            embeddings = _make_embeddings_local(EMBED_MODEL_PATH)
        except Exception as e:
            if _is_disk_full_error(e) or "no space left" in str(e).lower():
                print("[model_llm] Hết dung lượng tải model → fallback Remote Embeddings.")
                embeddings = _make_embeddings_remote(EMBED_MODEL_ID)
            else:
                raise

    # ====== FAISS ======
    # Ưu tiên dùng /data nếu tồn tại (Persistent Storage trên Spaces)
    default_faiss_dir = "/data/faiss" if os.path.isdir("/data") else "./src/app/vectorstore/FAISS_Vector_All"
    FAISS_DIR = _abs(os.getenv("FAISS_DIR") or default_faiss_dir)
    # Nếu không có thư mục FAISS local → thử tải từ Hub (nếu có config)
    faiss_load_dir = _maybe_download_faiss_from_hub(FAISS_DIR)

    if not os.path.isdir(faiss_load_dir):
        raise FileNotFoundError(
            f"FAISS directory không tồn tại: {faiss_load_dir}. "
            f"Hãy: (1) commit index vào repo, hoặc (2) cấu hình FAISS_HUB_REPO/FAISS_HUB_SUBDIR để tự tải, "
            f"hoặc (3) mount Persistent Storage và build index vào {FAISS_DIR}."
        )

    vector_store = FAISS.load_local(
        faiss_load_dir,
        embeddings,
        allow_dangerous_deserialization=True,
    )

    # (Tuỳ chọn) Kiểm tra khớp dimension giữa embedding & FAISS index
    try:
        expected_dim = getattr(vector_store.index, "d", None)
        if expected_dim:
            qdim = len(embeddings.embed_query("dimension probe"))
            if qdim != expected_dim:
                raise ValueError(
                    f"Embedding dimension ({qdim}) khác với FAISS index ({expected_dim}). "
                    f"Hãy rebuild FAISS đúng model: {EMBED_MODEL_ID}"
                )
    except Exception:
        # Bỏ qua kiểm tra nếu môi trường không có faiss hoặc lần đầu gọi remote
        pass

    # ====== Retriever ======
    if callable(build_hybrid_retriever):
        retriever = build_hybrid_retriever(vector_store)
    else:
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
