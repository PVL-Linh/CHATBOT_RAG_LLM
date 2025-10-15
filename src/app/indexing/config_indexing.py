from __future__ import annotations

import os
from pathlib import Path

# =======================
# Đường dẫn & cấu hình cơ bản
# =======================

# .../src/app
APP_DIR: Path = Path(__file__).resolve().parents[1]

# Root chứa các thư mục FAISS (đúng với cây hiện tại của bạn)
#   - src/app/vectorstore/FAISS_Vector_All
#   - src/app/vectorstore/FAISS_Vector_HR
DEPTS_ROOT_DEFAULT: Path = APP_DIR / "vectorstore"

# Root dữ liệu text (ưu tiên tìm Data/<dept>, fallback Data/Data_All)
#   - src/app/Data/HR
#   - src/app/Data/Data_All
DATA_ROOT_DEFAULT: Path = APP_DIR / "Data"

# Model embeddings (mặc định local folder; có thể override bằng ENV EMBED_MODEL_DIR)
EMBED_MODEL_NAME: str = os.environ.get(
    "EMBED_MODEL_DIR",
    str(APP_DIR / "models" / "local_multilingual_e5_large"),
)

# Tham số chunking khuyến nghị
CHUNK_SIZE: int = int(os.environ.get("CHUNK_SIZE", 1200))
CHUNK_OVERLAP: int = int(os.environ.get("CHUNK_OVERLAP", 300))
if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE // 4)

# Thư mục lưu bản gốc file khi thêm qua API (audit)
UPDATE_PREFIX: str = "update_"


# =======================
# Helpers cho Embeddings
# =======================

def _cuda_ok() -> bool:
    try:
        import torch  # type: ignore
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def build_embeddings():
    """
    Trả về bộ (embeddings, device, batch_size)
    - Tự nhận biết CUDA nếu có.
    - Có thể đổi model qua ENV EMBED_MODEL_DIR (ví dụ dùng model HF online).
    """
    from langchain_huggingface import HuggingFaceEmbeddings  # lazy import

    device = "cuda" if _cuda_ok() else "cpu"
    batch = int(os.environ.get("EMB_BATCH", 32 if device == "cuda" else 8))

    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_NAME,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch},
    )
    return emb, device, batch
