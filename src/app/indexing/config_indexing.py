from __future__ import annotations
from pathlib import Path
import os

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "250"))

THIS_DIR = Path(__file__).resolve().parent
APP_DIR = THIS_DIR.parent
DEPTS_ROOT_DEFAULT: Path = APP_DIR / "vectorstore"
CANONICAL_DEPTS = ("Data_All", "HR", "Accountant")


def canonical_dept(name: str | None) -> str | None:
    if not name:
        return None

    n = str(name).strip().lower()

    if n in ("data_all", "faiss_vector_data_all", "faiss-vector-data-all", "vector_data_all"):
        return "Data_All"

    if n in ("hr", "faiss_vector_hr", "faiss-vector-hr", "humanresources"):
        return "HR"

    if n in ("accountant", "faiss_vector_accountant", "faiss-vector-accountant"):
        return "Accountant"
    return name


def dept_paths(root: str | Path | None, dept: str):
    d = canonical_dept(dept)
    if not d:
        raise ValueError("dept is required")

    root_path = Path(root) if root else DEPTS_ROOT_DEFAULT
    root_path = root_path.resolve()

    # Map data_dir theo cấu trúc thật
    if d == "Data_All":
        data_dir = (APP_DIR / "Data" / "Data_All").resolve()
    else:
        data_dir = (APP_DIR / "Data" / d).resolve()

    index_dir = (root_path / f"FAISS_Vector_{d}").resolve()
    update_dir = (root_path / f"update_{d.lower()}").resolve()
    dept_dir = (root_path / d).resolve()
    corpus_path = (index_dir / "corpus.jsonl").resolve()

    return (str(dept_dir), str(data_dir), str(index_dir), str(corpus_path), str(update_dir))


def list_departments(root: str | Path | None) -> list[str]:
    return list(CANONICAL_DEPTS)

def all_known_paths(root: str | Path | None, dept: str | None, ensure: bool = False) -> dict:
    def _one(dname: str):
        _dept_dir, _data_dir, _index_dir, _corpus, _update = dept_paths(root, dname)
        if ensure:
            for p in (_dept_dir, _data_dir, _index_dir, _update):
                Path(p).mkdir(parents=True, exist_ok=True)
        return {
            "root": str(Path(root or DEPTS_ROOT_DEFAULT).resolve()),
            "dept_dir": _dept_dir,
            "data_dir": _data_dir,
            "index_dir": _index_dir,
            "corpus": _corpus,
            "update_dir": _update,
        }

    if dept:
        cd = canonical_dept(dept)
        return {cd: _one(cd)}
    out: dict = {}
    for d in list_departments(root):
        out[d] = _one(d)
    return out
