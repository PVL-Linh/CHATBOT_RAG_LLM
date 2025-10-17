# -*- coding: utf-8 -*-
import json, os, hashlib
from typing import Dict, List, Optional, Tuple
from app.config.paths import DATA_DIR_HR
from app.config.config_HR import SOURCE_REGISTRY_PATH, STRICT_SOURCE_MATCH_HR

_Registry: List[Dict] = []
_ByPath: Dict[str, Dict] = {}
_ByType: Dict[str, List[Dict]] = {}

def _sha256_file(full_path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(full_path, "rb") as f:
            for chunk in iter(lambda: f.read(1<<20), b""):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None

def load_registry() -> List[Dict]:
    global _Registry, _ByPath, _ByType
    _Registry, _ByPath, _ByType = [], {}, {}
    if not SOURCE_REGISTRY_PATH or not os.path.isfile(SOURCE_REGISTRY_PATH):
        return _Registry
    try:
        with open(SOURCE_REGISTRY_PATH, "r", encoding="utf-8") as f:
            arr = json.load(f)
            if not isinstance(arr, list): return []
            for rec in arr:
                path = (rec.get("path") or "").strip()
                if not path: continue
                rec["path"] = path
                _Registry.append(rec)
                _ByPath[path] = rec
                _ByType.setdefault((rec.get("type") or "").strip(), []).append(rec)
            return _Registry
    except:
        return []

def get_by_type(doc_type: str) -> List[Dict]:
    if not _Registry: load_registry()
    return list(_ByType.get(doc_type, []))

def get_by_path(path: str) -> Optional[Dict]:
    if not _Registry: load_registry()
    return _ByPath.get(path)

def verify_hash_if_present(rec: Dict) -> bool:
    sha = (rec.get("sha256") or "").strip().lower()
    if not sha: return True
    full = os.path.join(DATA_DIR_HR, rec["path"])
    calc = _sha256_file(full)
    return (calc == sha)

def pick_best_from_scored(doc_type: str, scored_sources: List[Tuple[str,float]]) -> Optional[str]:
    if not _Registry: load_registry()
    allowed = { (r["path"]): r for r in get_by_type(doc_type) }
    if not allowed:
        return scored_sources[0][0] if scored_sources else None
    for src, _ in scored_sources:
        if src in allowed:
            return src
    return None
