from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from app.indexing.config_indexing import DEPTS_ROOT_DEFAULT


def canonical_dept(dept: Optional[str]) -> Optional[str]:
    if not dept:
        return None
    d = str(dept).strip()
    low = d.lower()
    if low in ("hr",):
        return "HR"
    if low in ("Data_All", "default"):
        return "Data_All"
    if low in ("accoutant"):
        return "Accountant"
    return d

def _std_paths_for_dept(root: str, dept: str) -> Dict[str, str]:
    root_dir = Path(root or DEPTS_ROOT_DEFAULT).resolve()
    app_dir = root_dir.parent
    data_dir = app_dir / "Data" / dept
    index_dir = root_dir / f"FAISS_Vector_{dept}"
    corpus = index_dir / "corpus.jsonl"
    update_dir = root_dir / f"update_{dept.lower()}"
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
    root_effective = str(root or DEPTS_ROOT_DEFAULT)

    result: Dict[str, Dict[str, str]] = {}

    for d in ("Data_All", "HR", "Accountant"):
        info = _std_paths_for_dept(root_effective, d)
        result[d] = info
    cd = canonical_dept(dept)
    if cd and cd not in result:
        result[cd] = _std_paths_for_dept(root_effective, cd)

    if ensure:
        for d, info in result.items():
            for key in ("dept_dir", "data_dir", "index_dir", "update_dir"):
                try:
                    os.makedirs(info[key], exist_ok=True)
                except Exception:
                    pass

    return result

def list_departments(root: Optional[str] = None) -> List[str]:
    mp = all_known_paths(root=root, ensure=False)
    return sorted(k for k in mp.keys())

def dept_paths(root: Optional[str], dept: str, ensure: bool = False) -> Tuple[str, str, str, str, str]:
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

def rel_from_data_dir(path: str, data_dir: Optional[str] = None) -> str:
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
