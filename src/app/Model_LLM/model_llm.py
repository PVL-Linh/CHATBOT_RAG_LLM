from __future__ import annotations
import os
import errno
from pathlib import Path
from typing import Optional, Tuple, Union
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="huggingface_hub.file_download")
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub.file_download")
try:
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception:
    from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings as LCEmbeddings
from langchain_community.vectorstores import FAISS
try:
    from app.Model_LLM.hybrid_retriever import build_hybrid_retriever
except Exception:
    build_hybrid_retriever = None

from google import genai as genai_new
from google.genai import types as genai_types
from huggingface_hub import snapshot_download

from app.config.paths import EMBED_MODEL_DIR, EMBED_REVISION, EMBED_MODEL_ID
from app.config.settings import Gemini_Config_LLM
from app.config.llm_paths import PATHS


# =========================
# Helpers
# =========================
def _repo_root() -> Path:
    """Gốc repo để join path tương đối khi REPO_ROOT chưa set."""
    return Path(__file__).resolve().parents[3]


def _as_path(p: Union[str, Path, None]) -> Optional[Path]:
    """Coerce sang Path (hoặc None)."""
    if p is None:
        return None
    return p if isinstance(p, Path) else Path(p)


def _abs(p: Union[str, Path, None], base: Union[str, Path, None] = None) -> Optional[str]:
    """
    Trả về đường dẫn tuyệt đối dạng str (hoặc None).
    - Chấp nhận str|Path|None.
    - base: mặc định dùng REPO_ROOT hoặc _repo_root().
    """
    if p is None:
        return None
    pth = _as_path(p)
    b = _as_path(base) or _as_path(os.getenv("REPO_ROOT")) or _repo_root()
    return str((pth if pth.is_absolute() else (b / pth)).resolve())


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


# =========================
# Embedding model helpers
# =========================
def ensure_local_hf_model(
    local_dir: Union[str, Path, None],
    model_id: str,
    revision: Optional[str] = None
) -> str:
    """
    Đảm bảo model HuggingFace có mặt ở local_dir. Trả về đường dẫn (str).

    - Nếu local_dir không truyền (None) -> dùng PATHS.embed_local_fallback_dir
    - Có thể override fallback qua ENV: EMBED_LOCAL_FALLBACK_DIR
    """
    local_dir_str = _abs(local_dir) or PATHS.embed_local_fallback_dir
    Path(local_dir_str).mkdir(parents=True, exist_ok=True)

    has_config = Path(local_dir_str, "config.json").exists()
    has_weights = any(Path(local_dir_str, fname).exists() for fname in ("pytorch_model.bin", "model.safetensors"))
    if has_config and has_weights:
        return local_dir_str

    token = getattr(Gemini_Config_LLM, "token", None) or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    force = bool(getattr(Gemini_Config_LLM, "force", False))

    try:
        print(f"[model_llm] Tải model '{model_id}' về: {local_dir_str} (revision={revision or 'default'})")
        snapshot_download(
            repo_id=model_id,
            revision=revision,
            local_dir=local_dir_str,
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
            f"Không tải được model {model_id} về {local_dir_str}. "
            f"Kiểm tra mạng/HF_TOKEN (nếu repo private). Chi tiết: {e}"
        )

    has_config = Path(local_dir_str, "config.json").exists()
    has_weights = any(Path(local_dir_str, fname).exists() for fname in ("pytorch_model.bin", "model.safetensors"))
    if not (has_config and has_weights):
        raise RuntimeError(f"Model {model_id} tải chưa đủ file cần thiết trong {local_dir_str}.")

    return local_dir_str


def _make_embeddings_local(model_path_or_name: Union[str, Path]) -> LCEmbeddings:
    """Embeddings LOCAL: ưu tiên GPU nếu có, fallback CPU."""
    model_path_or_name = str(model_path_or_name)

    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False

    force_device = (os.getenv("EMBED_DEVICE") or "").strip().lower()
    if force_device == "gpu":
        force_device = "cuda"

    if force_device in ("cpu", "cuda"):
        device = force_device
    else:
        use_gpu = (os.getenv("EMBED_USE_GPU") or "0").strip() == "1"
        device = "cuda" if (use_gpu and has_cuda) else "cpu"

    batch = int(os.getenv("EMBED_BATCH", "16"))

    try:
        model_kwargs = {"device": device}
        return HuggingFaceEmbeddings(
            model_name=model_path_or_name,
            model_kwargs=model_kwargs,
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
    Embeddings REMOTE qua Hugging Face Inference.
    Cần HUGGINGFACEHUB_API_TOKEN hoặc HF_TOKEN.
    """
    api_key = (
        os.getenv("HUGGINGFACEHUB_API_TOKEN")
        or os.getenv("HF_TOKEN")
        or getattr(Gemini_Config_LLM, "api_key", None)
    )
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


# =========================
# FAISS helpers
# =========================
def _maybe_download_faiss_from_hub(default_dir: Union[str, Path]) -> str:
    """
    Nếu FAISS_DIR chưa tồn tại và có cấu hình repo HF, tải index từ Hub về runtime.
    Trả về đường dẫn để FAISS.load_local().

    ENV:
      - FAISS_HUB_REPO (vd: username/my-faiss-index)
      - FAISS_HUB_REPO_TYPE (override PATHS.faiss_hub_repo_type)
      - FAISS_HUB_SUBDIR (override PATHS.faiss_hub_subdir)
      - FAISS_LOCAL_DIR (override PATHS.faiss_default_dir)
    """
    local_dir = os.getenv("FAISS_LOCAL_DIR") or str(default_dir)
    local_dir = _abs(local_dir, base=PATHS.repo_root) or PATHS.faiss_default_dir

    # Nếu đã có sẵn dir local -> dùng luôn
    if Path(local_dir).is_dir():
        return local_dir

    repo_id = os.getenv("FAISS_HUB_REPO")
    if not repo_id:
        return local_dir

    # Cho phép env override repo_type / subdir trên PATHS
    repo_type = os.getenv("FAISS_HUB_REPO_TYPE") or PATHS.faiss_hub_repo_type
    subdir = os.getenv("FAISS_HUB_SUBDIR") or PATHS.faiss_hub_subdir

    print(f"[model_llm] Tải FAISS index từ Hub: {repo_type}:{repo_id}/{subdir}")
    snap_path = snapshot_download(
        repo_id=repo_id,
        repo_type=repo_type,
        allow_patterns=[f"{subdir}/*", f"{subdir}/**/*", "*.faiss", "*.pkl", "*.json"],
    )
    faiss_load_dir = str(Path(snap_path, subdir))
    return faiss_load_dir


def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY (hoặc GOOGLE_API_KEY) trong biến môi trường.")
    return genai_new.Client(api_key=api_key)


# =========================
# Factory chính
# =========================
def LLM_model(
    bm25_folder: Optional[Union[str, Path]] = None,
    corpus_path: Optional[Union[str, Path]] = None,
) -> Tuple[
    LCEmbeddings,          # embeddings (local hoặc remote)
    FAISS,                 # vector_store
    object,                # retriever
    genai_new.Client,      # gclient
    str,                   # GEMINI_MODEL
    genai_types.GenerateContentConfig,  # GEN_CFG
]:
    """
    Trả về: embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG

    ENV:
      - EMBED_MODEL_ID / EMBED_REVISION / EMBED_MODEL_DIR
      - EMBED_FORCE_REMOTE (1|0|auto)
      - HUGGINGFACEHUB_API_TOKEN hoặc HF_TOKEN (remote)
      - FAISS_DIR / FAISS_LOCAL_DIR / FAISS_HUB_*
      - GEMINI_*

    Tham số:
      - bm25_folder: folder chứa .txt để build BM25 (None -> để hybrid_retriever dùng default DATA_DIR)
      - corpus_path: file corpus.jsonl tương ứng (None -> default trong hybrid_retriever)
    """

    # ====== Chọn LOCAL / REMOTE embeddings ======
    force_remote_env = (os.getenv("EMBED_FORCE_REMOTE", "auto").strip().lower())
    running_on_spaces = bool(os.getenv("SPACE_ID"))
    if force_remote_env in ("1", "true", "yes"):
        use_remote = True
    elif force_remote_env == "auto":
        use_remote = running_on_spaces
    else:
        use_remote = False

    # ====== Embeddings ======
    if use_remote:
        print("[model_llm] Dùng Remote Embeddings (Hugging Face Inference).")
        embeddings: LCEmbeddings = _make_embeddings_remote(EMBED_MODEL_ID)
    else:
        try:
            local_embed_dir = ensure_local_hf_model(
                local_dir=EMBED_MODEL_DIR,
                model_id=EMBED_MODEL_ID,
                revision=EMBED_REVISION,
            )
            embeddings = _make_embeddings_local(local_embed_dir)
        except Exception as e:
            if _is_disk_full_error(e) or "no space left" in str(e).lower():
                print("[model_llm] Hết dung lượng tải model → fallback Remote Embeddings.")
                embeddings = _make_embeddings_remote(EMBED_MODEL_ID)
            else:
                raise

    # ====== FAISS ======
    default_faiss_dir = PATHS.faiss_default_dir
    FAISS_DIR = _abs(os.getenv("FAISS_DIR") or default_faiss_dir, base=PATHS.repo_root) or default_faiss_dir

    faiss_load_dir = _maybe_download_faiss_from_hub(FAISS_DIR)
    if not Path(faiss_load_dir).is_dir():
        raise FileNotFoundError(
            f"FAISS directory không tồn tại: {faiss_load_dir}. "
            f"Hãy: (1) commit index vào repo, hoặc (2) cấu hình FAISS_HUB_REPO/FAISS_HUB_SUBDIR để tự tải, "
            f"hoặc (3) mount Persistent Storage và build index vào {FAISS_DIR}."
        )

    expected_hash = os.getenv("FAISS_EXPECTED_HASH")
    if expected_hash:
        from hashlib import sha256
        with open(f"{faiss_load_dir}/index.faiss", "rb") as f:
            file_hash = sha256(f.read()).hexdigest()
        if file_hash != expected_hash:
            raise ValueError("FAISS index hash mismatch - potential tampering")

    vector_store = FAISS.load_local(
        faiss_load_dir,
        embeddings,
        allow_dangerous_deserialization=True,
    )

    # (Tuỳ chọn) Kiểm tra dimension khớp
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
        pass

    # ====== Chuẩn hoá bm25_folder / corpus_path từ caller ======
    bm25_folder_abs = _abs(bm25_folder, base=PATHS.repo_root) if bm25_folder is not None else None
    corpus_path_abs = _abs(corpus_path, base=PATHS.repo_root) if corpus_path is not None else None

    # ====== Retriever ======
    if callable(build_hybrid_retriever):
        retriever = build_hybrid_retriever(
            vector_store,
            folder=bm25_folder_abs,
            corpus_path=corpus_path_abs,
        )
    else:
        retriever = vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 7},
        )

    # ====== Gemini ======
    gclient = get_gemini_client()
    GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemma-3-12b-it")
    GEN_CFG = genai_types.GenerateContentConfig(
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
        max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "4000")),
        top_p=float(os.getenv("GEMINI_TOP_P", "0.95")),
        top_k=int(os.getenv("GEMINI_TOP_K", "20")),
    )

    return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG




# from __future__ import annotations

# import os
# import errno
# from pathlib import Path
# from typing import Optional, Tuple, Union, Any

# # --- Optional: Ẩn warnings deprecate từ huggingface_hub ---
# import warnings
# warnings.filterwarnings("ignore", category=FutureWarning, module="huggingface_hub.file_download")
# warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub.file_download")

# # --- LangChain Embeddings (ưu tiên lib mới, fallback lib cũ) ---
# try:
#     from langchain_huggingface import HuggingFaceEmbeddings
# except Exception:
#     from langchain_community.embeddings import HuggingFaceEmbeddings
# from langchain_core.embeddings import Embeddings as LCEmbeddings
# from langchain_community.vectorstores import FAISS

# try:
#     from app.Model_LLM.hybrid_retriever import build_hybrid_retriever
# except Exception:
#     build_hybrid_retriever = None

# from google import genai as genai_new
# from google.genai import types as genai_types
# from huggingface_hub import snapshot_download

# from app.config.paths import EMBED_MODEL_DIR, EMBED_REVISION, EMBED_MODEL_ID, FAISS_ALL_DIR
# from app.config.settings import Gemini_Config_LLM


# # =========================
# # Helpers
# # =========================
# def _repo_root() -> Path:
#     """Gốc repo để join path tương đối khi REPO_ROOT chưa set."""
#     # __file__ = .../src/app/Model_LLM/model_llm.py
#     return Path(__file__).resolve().parents[3]


# def _as_path(p: Union[str, Path, None]) -> Optional[Path]:
#     """Coerce sang Path (hoặc None)."""
#     if p is None:
#         return None
#     return p if isinstance(p, Path) else Path(p)


# def _abs(p: Union[str, Path, None], base: Union[str, Path, None] = None) -> Optional[str]:
#     """
#     Trả về đường dẫn tuyệt đối dạng str (hoặc None).
#     - Chấp nhận str|Path|None.
#     - base: mặc định dùng REPO_ROOT hoặc _repo_root().
#     """
#     if p is None:
#         return None
#     pth = _as_path(p)
#     b = _as_path(base) or _as_path(os.getenv("REPO_ROOT")) or _repo_root()
#     return str((pth if pth.is_absolute() else (b / pth)).resolve())


# def _ensure_exists(path: Union[str, Path], what: str):
#     if not Path(path).exists():
#         raise FileNotFoundError(f"{what} không tồn tại: {path}")


# def _is_disk_full_error(exc: Exception) -> bool:
#     s = str(exc).lower()
#     eno = getattr(exc, "errno", None)
#     return (
#         isinstance(exc, OSError) and eno == errno.ENOSPC
#         or "no space left" in s
#         or "disk full" in s
#         or "insufficient space" in s
#         or "no enough space" in s
#     )


# def ensure_local_hf_model(
#     local_dir: Union[str, Path, None],
#     model_id: str,
#     revision: Optional[str] = None
# ) -> str:
#     """
#     Đảm bảo model HuggingFace có mặt ở local_dir. Trả về đường dẫn (str).
#     """
#     local_dir_str = _abs(local_dir) or str((_repo_root() / "models" / "local_multilingual_e5_large").resolve())
#     Path(local_dir_str).mkdir(parents=True, exist_ok=True)

#     has_config = Path(local_dir_str, "config.json").exists()
#     has_weights = any(Path(local_dir_str, fname).exists() for fname in ("pytorch_model.bin", "model.safetensors"))
#     if has_config and has_weights:
#         return local_dir_str

#     token = getattr(Gemini_Config_LLM, "token", None) or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
#     force = bool(getattr(Gemini_Config_LLM, "force", False))

#     try:
#         print(f"[model_llm] Tải model '{model_id}' về: {local_dir_str} (revision={revision or 'default'})")
#         snapshot_download(
#             repo_id=model_id,
#             revision=revision,
#             local_dir=local_dir_str,
#             token=token,
#             force_download=force,
#             allow_patterns=[
#                 "config.json",
#                 "pytorch_model.bin",
#                 "*.safetensors",
#                 "tokenizer.json",
#                 "tokenizer_config.json",
#                 "special_tokens_map.json",
#                 "sentencepiece.*",
#                 "spiece.*",
#                 "vocab.*",
#             ],
#         )
#     except Exception as e:
#         raise RuntimeError(
#             f"Không tải được model {model_id} về {local_dir_str}. "
#             f"Kiểm tra mạng/HF_TOKEN (nếu repo private). Chi tiết: {e}"
#         )

#     has_config = Path(local_dir_str, "config.json").exists()
#     has_weights = any(Path(local_dir_str, fname).exists() for fname in ("pytorch_model.bin", "model.safetensors"))
#     if not (has_config and has_weights):
#         raise RuntimeError(f"Model {model_id} tải chưa đủ file cần thiết trong {local_dir_str}.")

#     return local_dir_str


# def _make_embeddings_local(model_path_or_name: Union[str, Path]) -> LCEmbeddings:
#     """Embeddings LOCAL: ưu tiên GPU nếu có, fallback CPU."""
#     model_path_or_name = str(model_path_or_name)

#     try:
#         import torch
#         has_cuda = torch.cuda.is_available()
#     except Exception:
#         has_cuda = False

#     force_device = (os.getenv("EMBED_DEVICE") or "").strip().lower()
#     if force_device == "gpu":
#         force_device = "cuda"

#     if force_device in ("cpu", "cuda"):
#         device = force_device
#     else:
#         use_gpu = (os.getenv("EMBED_USE_GPU") or "0").strip() == "1"
#         device = "cuda" if (use_gpu and has_cuda) else "cpu"

#     batch = int(os.getenv("EMBED_BATCH", "16"))

#     try:
#         model_kwargs = {"device": device}
#         # if os.environ.get("EMBED_QUANTIZE", "0") == "1":
#         #     from transformers import BitsAndBytesConfig
#         #     model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
#         return HuggingFaceEmbeddings(
#             model_name=model_path_or_name,
#             model_kwargs=model_kwargs,
#             encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
#         )
#     except Exception as e:
#         msg = str(e).lower()
#         if any(k in msg for k in ("cuda", "out of memory", "cublas", "cudnn")):
#             return HuggingFaceEmbeddings(
#                 model_name=model_path_or_name,
#                 model_kwargs={"device": "cpu"},
#                 encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
#             )
#         raise


# def _make_embeddings_remote(model_id: str) -> LCEmbeddings:
#     """
#     Embeddings REMOTE qua Hugging Face Inference.
#     Cần HUGGINGFACEHUB_API_TOKEN hoặc HF_TOKEN.
#     """
#     api_key = (
#         os.getenv("HUGGINGFACEHUB_API_TOKEN")
#         or os.getenv("HF_TOKEN")
#         or getattr(Gemini_Config_LLM, "api_key", None)
#     )
#     if not api_key:
#         raise RuntimeError("Thiếu HUGGINGFACEHUB_API_TOKEN/HF_TOKEN để dùng Hugging Face Inference.")

#     try:
#         from langchain_huggingface import HuggingFaceEndpointEmbeddings  # type: ignore
#         return HuggingFaceEndpointEmbeddings(
#             model=model_id,
#             task="feature-extraction",
#             huggingfacehub_api_token=api_key,
#         )
#     except Exception:
#         from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings  # type: ignore
#         return HuggingFaceInferenceAPIEmbeddings(
#             api_key=api_key,
#             model_name=model_id,
#         )


# def _maybe_download_faiss_from_hub(default_dir: Union[str, Path]) -> str:
#     """
#     Nếu FAISS_DIR chưa tồn tại và có cấu hình repo HF, tải index từ Hub về runtime.
#     Trả về đường dẫn để FAISS.load_local().
#     ENV:
#       - FAISS_HUB_REPO (vd: username/my-faiss-index)
#       - FAISS_HUB_REPO_TYPE = dataset|model (mặc định: dataset)
#       - FAISS_HUB_SUBDIR (vd: FAISS_Vector_All)
#       - FAISS_LOCAL_DIR (override đường dẫn local nếu muốn)
#     """
#     local_dir = os.getenv("FAISS_LOCAL_DIR") or str(default_dir)
#     local_dir = _abs(local_dir) or str((_repo_root() / "vectorstore" / "FAISS_Vector_All").resolve())

#     if Path(local_dir).is_dir():
#         return local_dir

#     repo_id = os.getenv("FAISS_HUB_REPO")
#     if not repo_id:
#         return local_dir

#     repo_type = os.getenv("FAISS_HUB_REPO_TYPE") or getattr(Gemini_Config_LLM, "repo_type", "dataset") or "dataset"
#     subdir = os.getenv("FAISS_HUB_SUBDIR") or "./src/app/vectorstore/FAISS_Vector_All" or getattr(Gemini_Config_LLM, "subdir", Path(FAISS_ALL_DIR).name)


#     print(f"[model_llm] Tải FAISS index từ Hub: {repo_type}:{repo_id}/{subdir}")
#     snap_path = snapshot_download(
#         repo_id=repo_id,
#         repo_type=repo_type,
#         allow_patterns=[f"{subdir}/*", f"{subdir}/**/*", "*.faiss", "*.pkl", "*.json"],
#     )
#     faiss_load_dir = str(Path(snap_path, subdir))
#     return faiss_load_dir


# def get_gemini_client():
#     api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
#     if not api_key:
#         raise RuntimeError("Thiếu GEMINI_API_KEY (hoặc GOOGLE_API_KEY) trong biến môi trường.")
#     return genai_new.Client(api_key=api_key)


# # =========================
# # Factory chính
# # =========================
# def LLM_model() -> Tuple[
#     LCEmbeddings,          # embeddings (local hoặc remote)
#     FAISS,                 # vector_store
#     object,                # retriever
#     genai_new.Client,      # gclient
#     str,                   # GEMINI_MODEL
#     genai_types.GenerateContentConfig,  # GEN_CFG
# ]:
#     """
#     Trả về: embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG
#     ENV:
#       - EMBED_MODEL_ID / EMBED_REVISION / EMBED_MODEL_DIR
#       - EMBED_FORCE_REMOTE (1|0|auto)
#       - HUGGINGFACEHUB_API_TOKEN hoặc HF_TOKEN (remote)
#       - FAISS_DIR / FAISS_LOCAL_DIR / FAISS_HUB_*
#       - GEMINI_*
#     """

#     force_remote_env = (os.getenv("EMBED_FORCE_REMOTE", "auto").strip().lower())
#     running_on_spaces = bool(os.getenv("SPACE_ID"))
#     if force_remote_env in ("1", "true", "yes"):
#         use_remote = True
#     elif force_remote_env == "auto":
#         use_remote = running_on_spaces
#     else:
#         use_remote = False

#     # ====== Embeddings ======
#     if use_remote:
#         print("[model_llm] Dùng Remote Embeddings (Hugging Face Inference).")
#         embeddings: LCEmbeddings = _make_embeddings_remote(EMBED_MODEL_ID)
#     else:
#         try:
#             local_embed_dir = ensure_local_hf_model(
#                 local_dir=EMBED_MODEL_DIR,
#                 model_id=EMBED_MODEL_ID,
#                 revision=EMBED_REVISION,
#             )
#             embeddings = _make_embeddings_local(local_embed_dir)
#         except Exception as e:
#             if _is_disk_full_error(e) or "no space left" in str(e).lower():
#                 print("[model_llm] Hết dung lượng tải model → fallback Remote Embeddings.")
#                 embeddings = _make_embeddings_remote(EMBED_MODEL_ID)
#             else:
#                 raise

#     # ====== FAISS ======
#     default_faiss_dir = _abs(str(FAISS_ALL_DIR)) or str((_repo_root() / "vectorstore" / "FAISS_Vector_All").resolve())
#     FAISS_DIR = _abs(os.getenv("FAISS_DIR") or default_faiss_dir) or default_faiss_dir

#     faiss_load_dir = _maybe_download_faiss_from_hub(FAISS_DIR)
#     if not Path(faiss_load_dir).is_dir():
#         raise FileNotFoundError(
#             f"FAISS directory không tồn tại: {faiss_load_dir}. "
#             f"Hãy: (1) commit index vào repo, hoặc (2) cấu hình FAISS_HUB_REPO/FAISS_HUB_SUBDIR để tự tải, "
#             f"hoặc (3) mount Persistent Storage và build index vào {FAISS_DIR}."
#         )

#     expected_hash = os.getenv("FAISS_EXPECTED_HASH")
#     if expected_hash:
#         from hashlib import sha256
#         with open(f"{faiss_load_dir}/index.faiss", "rb") as f:
#             file_hash = sha256(f.read()).hexdigest()
#         if file_hash != expected_hash:
#             raise ValueError("FAISS index hash mismatch - potential tampering")
#     vector_store = FAISS.load_local(
#         faiss_load_dir,
#         embeddings,
#         allow_dangerous_deserialization=True,
#     )
#     # print("[WARNING] Using dangerous deserialization - ensure source trusted")

#     # (Tuỳ chọn) Kiểm tra dimension khớp
#     try:
#         expected_dim = getattr(vector_store.index, "d", None)
#         if expected_dim:
#             qdim = len(embeddings.embed_query("dimension probe"))
#             if qdim != expected_dim:
#                 raise ValueError(
#                     f"Embedding dimension ({qdim}) khác với FAISS index ({expected_dim}). "
#                     f"Hãy rebuild FAISS đúng model: {EMBED_MODEL_ID}"
#                 )
#     except Exception:
#         pass

#     # ====== Retriever ======
#     if callable(build_hybrid_retriever):
#         retriever = build_hybrid_retriever(vector_store)
#     else:
#         retriever = vector_store.as_retriever(search_type="mmr", search_kwargs={"k": 11})

#     # ====== Gemini ======
#     gclient = get_gemini_client()
#     GEMINI_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
#     GEN_CFG = genai_types.GenerateContentConfig(
#         temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
#         max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT", "6000")),
#         top_p=float(os.getenv("GEMINI_TOP_P", "0.95")),
#         top_k=int(os.getenv("GEMINI_TOP_K", "40")),
#     )

#     return embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG



