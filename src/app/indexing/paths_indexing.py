# app/indexing/paths_indexing.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from app.indexing.config_indexing import DEPTS_ROOT_DEFAULT

# ===== Helpers =====

def canonical_dept(dept: Optional[str]) -> Optional[str]:
    if not dept:
        return None
    d = str(dept).strip()
    low = d.lower()
    if low in ("hr",):
        return "HR"
    if low in ("all", "default"):
        return "ALL"
    # Nếu có dept khác, chuẩn hoá theo upper cho nhất quán
    return d.upper()

def _std_paths_for_dept(root: str, dept: str) -> Dict[str, str]:
    """
    Chuẩn hoá đường dẫn cho 2 phòng ban chuẩn: HR, ALL.
    Không quét thư mục để tránh sinh thêm key rác.
    """
    root_dir = Path(root or DEPTS_ROOT_DEFAULT).resolve()
    app_dir = root_dir.parent  # .../vectorstore/ -> parent = .../app

    # Data nằm dưới app/Data/<DEPT>
    data_dir = app_dir / "Data" / dept

    # Index nằm dưới vectorstore/FAISS_Vector_<DEPT>
    index_dir = root_dir / f"FAISS_Vector_{dept}"

    # Corpus file (nếu chưa có cũng không sao)
    corpus = index_dir / "corpus.jsonl"

    # update dir theo convention cũ
    update_dir = root_dir / f"update_{dept.lower()}"

    # dept_dir chỉ là thư mục “nhãn” trong root (không nhất thiết dùng)
    dept_dir = root_dir / dept

    return {
        "root": str(root_dir),
        "dept_dir": str(dept_dir),
        "data_dir": str(data_dir),
        "index_dir": str(index_dir),
        "corpus": str(corpus),
        "update_dir": str(update_dir),
    }

def all_known_paths(root: Optional[str] = None,
                    dept: Optional[str] = None,
                    ensure: bool = False) -> Dict[str, Dict[str, str]]:
    """
    Trả về mapping chuẩn chỉ gồm: HR, ALL (và dept chỉ định nếu khác).
    Không quét filesystem để tránh sinh thêm mục như FAISS_Vector_All/HR...
    """
    root_effective = str(root or DEPTS_ROOT_DEFAULT)

    result: Dict[str, Dict[str, str]] = {}

    # 2 phòng ban mặc định
    for d in ("ALL", "HR"):
        info = _std_paths_for_dept(root_effective, d)
        result[d] = info

    # Nếu người gọi truyền dept khác hai loại trên, thêm vào theo cùng convention
    cd = canonical_dept(dept)
    if cd and cd not in result:
        result[cd] = _std_paths_for_dept(root_effective, cd)

    # ensure: tạo folder nếu thiếu (index_dir, data_dir, update_dir, dept_dir)
    if ensure:
        for d, info in result.items():
            for key in ("dept_dir", "data_dir", "index_dir", "update_dir"):
                try:
                    os.makedirs(info[key], exist_ok=True)
                except Exception:
                    pass

    return result

def list_departments(root: Optional[str] = None) -> List[str]:
    """Danh sách phòng ban hợp lệ (mặc định: ALL, HR)."""
    mp = all_known_paths(root=root, ensure=False)
    # chỉ hiển thị key chuẩn, không trả về các key gây nhiễu
    return sorted(k for k in mp.keys())

def dept_paths(root: Optional[str], dept: str, ensure: bool = False) -> Tuple[str, str, str, str, str]:
    """
    Trả về 5-tuple: (dept_dir, data_dir, index_dir, corpus, update_dir)
    -> đúng với kỳ vọng của list_cmd.list_index_sources(...)
    """
    cd = canonical_dept(dept)
    if not cd:
        raise ValueError("dept is required")

    info_map = all_known_paths(root=root, dept=cd, ensure=ensure)
    if cd not in info_map:
        raise RuntimeError(f"Unknown dept: {dept}")

    info = info_map[cd]
    return (
        info["dept_dir"],
        info["data_dir"],
        info["index_dir"],
        info["corpus"],
        info["update_dir"],
    )

# ====== các hàm tiện ích mà add_indexing.py đang import ======

def rel_from_data_dir(path: str, data_dir: Optional[str] = None) -> str:
    """
    Trả về đường dẫn tương đối tính từ data_dir (dùng khi set metadata['source']).
    """
    base = Path(data_dir or (Path(DEPTS_ROOT_DEFAULT).parent / "Data")).resolve()
    ap = Path(path).resolve()
    try:
        rel = ap.relative_to(base)
        return str(rel).replace("\\", "/")
    except Exception:
        return str(ap).replace("\\", "/")

def list_txt_files_under(data_dir: str) -> List[str]:
    out: List[str] = []
    d = Path(data_dir)
    if not d.is_dir():
        return out
    for p in d.rglob("*.txt"):
        out.append(str(p))
    return out
