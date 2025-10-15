from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List

from .config_indexing import (
    DEPTS_ROOT_DEFAULT,
    DATA_ROOT_DEFAULT,
    UPDATE_PREFIX,
)

# =======================
# Dataclass gom đường dẫn
# =======================

@dataclass
class DepartmentPaths:
    dept: str
    dept_dir: Path     # container logic; với layout phẳng sẽ là vectorstore/
    data_dir: Path     # src/app/Data/<dept> hoặc Data/Data_All
    index_dir: Path    # src/app/vectorstore/FAISS_Vector_<DEPT> (phẳng) hoặc <dept>/Faiss_vector (fallback)
    corpus_path: Path  # <-- YÊU CẦU MỚI: LUÔN là index_dir / 'corpus.jsonl'
    update_dir: Path   # src/app/vectorstore/update_<dept>

    def ensure(self) -> "DepartmentPaths":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.update_dir.mkdir(parents=True, exist_ok=True)
        return self


# =======================
# Resolve root
# =======================

def get_root(root: Optional[str | Path]) -> Path:
    """
    Trả về Path root chuẩn. Nếu không truyền, dùng DEPTS_ROOT_DEFAULT.
    """
    return Path(root).resolve() if root else Path(DEPTS_ROOT_DEFAULT).resolve()


# =======================
# Layout resolver
# =======================

def dept_paths_dataclass(root: Optional[str | Path], dept: str, ensure: bool = True) -> DepartmentPaths:
    """
    Hỗ trợ 2 layout:

    A) PHẲNG (đúng cây hiện tại):
        vectorstore/
          ├── FAISS_Vector_ALL/
          ├── FAISS_Vector_HR/
          └── (corpus chính) FAISS_Vector_<DEPT>/corpus.jsonl
        data ưu tiên: Data/<dept>, fallback: Data/Data_All

    B) THEO THƯ MỤC (fallback):
        vectorstore/
          └── <dept>/
              ├── Faiss_vector/
              ├── Data_All/
              └── (corpus chính) Faiss_vector/corpus.jsonl
    """
    r = get_root(root)
    dept_norm = Path(dept).name
    dept_upper = dept_norm.upper()
    dept_lower = dept_norm.lower()

    # ---- Ưu tiên layout phẳng
    flat_index = r / f"FAISS_Vector_{dept_upper}"
    if flat_index.is_dir():
        index_dir = flat_index
        dept_dir = r  # container logic
        # YÊU CẦU MỚI: corpus chính nằm TRONG index_dir
        corpus = index_dir / "corpus.jsonl"
    else:
        # ---- Fallback: mỗi phòng ban là 1 thư mục
        dept_dir = r / dept_norm
        index_dir = dept_dir / "Faiss_vector"
        # corpus chính cũng nằm trong index_dir
        corpus = index_dir / "corpus.jsonl"

    # ---- Data dir: ưu tiên Data/<dept>, fallback Data/Data_All
    prefer = DATA_ROOT_DEFAULT / dept_norm
    data_dir = prefer if prefer.is_dir() else (DATA_ROOT_DEFAULT / "Data_All")

    update_dir = r / f"{UPDATE_PREFIX}{dept_lower}"

    dp = DepartmentPaths(
        dept=dept_norm,
        dept_dir=dept_dir,
        data_dir=data_dir,
        index_dir=index_dir,
        corpus_path=corpus,
        update_dir=update_dir,
    )
    return dp.ensure() if ensure else dp


def dept_paths(root: str | Path, dept: str) -> Tuple[str, str, str, str, str]:
    """
    API tiện lợi cho code cũ: trả về tuple string.
    """
    dp = dept_paths_dataclass(root, dept, ensure=True)
    return (
        str(dp.dept_dir),
        str(dp.data_dir),
        str(dp.index_dir),
        str(dp.corpus_path),
        str(dp.update_dir),
    )


# =======================
# Tiện ích liệt kê
# =======================

def list_departments(root: str | Path | None = None) -> List[str]:
    """
    Quét root để tìm các phòng ban theo cả 2 layout.
    - Layout phẳng: phát hiện thư mục bắt đầu bằng 'FAISS_Vector_'
    - Layout thư mục: phát hiện '<dept>/Faiss_vector'
    Kết quả trả lowercase, duy nhất, đã sort.
    """
    r = get_root(root)
    if not r.exists():
        return []

    out: List[str] = []

    # A) phẳng
    for p in r.iterdir():
        if p.is_dir() and p.name.startswith("FAISS_Vector_"):
            out.append(p.name.replace("FAISS_Vector_", "").lower())

    # B) theo thư mục
    for p in r.iterdir():
        if p.is_dir() and (p / "Faiss_vector").is_dir():
            out.append(p.name.lower())

    # dedupe + sort
    return sorted(list(dict.fromkeys(out)))


def all_known_paths(root: Optional[str | Path], dept: Optional[str], ensure: bool = False) -> dict:
    """
    Trả về thông tin tổng quan (depts_root, departments,...).
    Nếu có dept, trả thêm các đường dẫn cụ thể cho dept đó.
    Ngoài 'corpus' chính (trong index_dir), trả kèm 'new_corpus' (gợi ý vị trí để tạo mới trong update_dir).
    """
    r = get_root(root)
    info = {
        "depts_root": str(r),
        "departments": list_departments(r),
    }
    if dept:
        dp = dept_paths_dataclass(r, dept, ensure=ensure)
        dept_lower = Path(dp.dept).name.lower()
        info["dept_paths"] = {
            "dept_dir": str(dp.dept_dir),
            "data_dir": str(dp.data_dir),
            "index_dir": str(dp.index_dir),
            "corpus": str(dp.corpus_path),  # corpus chính
            "update_dir": str(dp.update_dir),
            # Gợi ý nơi tạo corpus mới (nếu bạn cần sinh file mới):
            "new_corpus": str(dp.update_dir / f"corpus_{dept_lower}.jsonl"),
        }
    return info


# =======================
# Một vài helper có thể được các module khác dùng lại
# =======================

def rel_from_data_dir(data_dir: str | Path, any_path: str | Path) -> str:
    """
    Trả về path tương đối tính từ data_dir (chuẩn hoá '/').
    """
    ap = str(Path(any_path).resolve())
    base = str(Path(data_dir).resolve())
    if ap.startswith(base):
        return str(Path(ap).relative_to(base)).replace("\\", "/")
    return Path(any_path).name.replace("\\", "/")


def list_txt_files_under(data_dir: str | Path) -> List[str]:
    out: List[str] = []
    base = Path(data_dir)
    if not base.is_dir():
        return out
    for root, _dirs, files in os.walk(base):
        for fn in files:
            if fn.lower().endswith(".txt"):
                out.append(str(Path(root) / fn))
    return out
