from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
from app.config.paths import FAISS_ALL_DIR
from app.config.settings import Gemini_Config_LLM


def _repo_root() -> Path:
    """Gốc repo để join path tương đối khi REPO_ROOT chưa set."""
    return Path(__file__).resolve().parents[3]


def _as_path(p: Union[str, Path, None]) -> Optional[Path]:
    if p is None:
        return None
    return p if isinstance(p, Path) else Path(p)


def _abs(p: Union[str, Path, None], base: Union[str, Path, None] = None) -> Optional[str]:
    """Trả về đường dẫn tuyệt đối dạng str (hoặc None)."""
    if p is None:
        return None
    pth = _as_path(p)
    b = _as_path(base) or _as_path(os.getenv("REPO_ROOT")) or _repo_root()
    return str((pth if pth.is_absolute() else (b / pth)).resolve())


@dataclass
class LLMPathConfig:
    """
    Chứa & chuẩn hoá các đường dẫn quan trọng cho LLM/RAG:
    - repo_root
    - embed_local_fallback_dir: nơi cache local embedding model
    - faiss_all_dir: thư mục FAISS_ALL_DIR (config gốc)
    - faiss_default_dir: FAISS_DIR mặc định (có thể override bằng ENV FAISS_DIR)
    - faiss_hub_subdir: subdir trên HuggingFace Hub khi tải FAISS
    - faiss_hub_repo_type: dataset | model (type của repo FAISS trên Hub)
    """
    repo_root: Path
    embed_local_fallback_dir: str
    faiss_all_dir: str
    faiss_default_dir: str
    faiss_hub_subdir: str
    faiss_hub_repo_type: str

    @classmethod
    def from_env(cls) -> "LLMPathConfig":
        rr = _repo_root()

        embed_local_fb = os.getenv("EMBED_LOCAL_FALLBACK_DIR")
        if embed_local_fb:
            embed_local_fb = _abs(embed_local_fb, base=rr)
        else:
            embed_local_fb = str((rr / "models" / "local_multilingual_e5_large").resolve())

        faiss_all = _abs(str(FAISS_ALL_DIR), base=rr) # or str((rr / "vectorstore" / "FAISS_Vector_All").resolve())
        faiss_default = _abs(os.getenv("FAISS_DIR") or faiss_all, base=rr) or faiss_all

        subdir_env = os.getenv("FAISS_HUB_SUBDIR")
        subdir_cfg = getattr(Gemini_Config_LLM, "subdir", None)
        faiss_subdir = subdir_env or subdir_cfg or Path(faiss_all).name

        repo_type_env = os.getenv("FAISS_HUB_REPO_TYPE")
        repo_type_cfg = getattr(Gemini_Config_LLM, "repo_type", "dataset")
        faiss_repo_type = repo_type_env or repo_type_cfg or "dataset"

        return cls(
            repo_root=rr,
            embed_local_fallback_dir=embed_local_fb,
            faiss_all_dir=faiss_all,
            faiss_default_dir=faiss_default,
            faiss_hub_subdir=faiss_subdir,
            faiss_hub_repo_type=faiss_repo_type,
        )

PATHS = LLMPathConfig.from_env()
