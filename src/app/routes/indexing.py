# -*- coding: utf-8 -*-
from __future__ import annotations
import os, tempfile, shutil
from pathlib import Path
from typing import List

from flask import Blueprint, request, jsonify
from app.Login.login_required import login_required
from app.indexing.config_indexing import DEPTS_ROOT_DEFAULT, all_known_paths, canonical_dept, list_departments
from app.indexing.list_cmd import list_index_sources
from app.indexing.add_indexing import add_files_to_index
from app.indexing.delete_indexing import delete_sources_from_index

indexing_bp = Blueprint("indexing", __name__, url_prefix="/api/indexing")

ALLOWED_EXTS = {".txt", ".pdf"}
def _allowed_file(filename: str) -> bool: return Path(filename).suffix.lower() in ALLOWED_EXTS

def _get_root() -> str:
    if request.is_json and request.json and request.json.get("root"):
        return os.path.abspath(request.json["root"])
    if request.form.get("root"):
        return os.path.abspath(request.form.get("root"))
    if request.args.get("root"):
        return os.path.abspath(request.args.get("root"))
    return str(DEPTS_ROOT_DEFAULT)

def _json_error(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code

@indexing_bp.get("/health")
@login_required(api=True)
def health():
    return jsonify({"ok": True, "service": "indexing"})

@indexing_bp.get("/paths")
@login_required(api=True)
def get_paths():
    root = request.args.get("root")
    dept = request.args.get("dept")
    ensure = request.args.get("ensure", "false").lower() in ("1","true","yes")
    info = all_known_paths(root=root, dept=dept, ensure=ensure)
    return jsonify({"ok": True, "data": info})

@indexing_bp.get("/list")
@login_required(api=True)
def list_api():
    root = _get_root()
    dept = canonical_dept(request.args.get("dept"))
    list_all = request.args.get("all", "false").lower() in ("1", "true", "yes")
    if list_all:
        depts = list_departments(root); payload = {}
        for d in depts:
            rows = list_index_sources(root, d)
            payload[d] = [{"source": s, "chunks": n} for s, n in rows]
        return jsonify({"ok": True, "root": root, "departments": payload})
    if not dept:
        return _json_error("Missing ?dept=... (or use ?all=1)")
    rows = list_index_sources(root, dept)
    return jsonify({"ok": True, "root": root, "dept": dept,
                    "sources": [{"source": s, "chunks": n} for s, n in rows]})

@indexing_bp.post("/add")
@login_required(api=True)
def add_api():
    root = _get_root()
    dept = (request.form.get("dept") or (request.json.get("dept") if request.is_json and request.json else None))
    if not dept: return _json_error("Missing 'dept'")
    saved_paths: List[str] = []

    # Upload multipart
    if request.files:
        tmp_dir = tempfile.mkdtemp(prefix="indexing_upload_")
        try:
            files = request.files.getlist("files")
            if not files: return _json_error("Form field 'files' is empty")
            for f in files:
                if not f or not f.filename: 
                    continue
                filename = Path(f.filename).name
                if not _allowed_file(filename):
                    return _json_error(f"Unsupported: {filename}. Allowed: {', '.join(sorted(ALLOWED_EXTS))}")
                dst = os.path.join(tmp_dir, filename)
                f.save(dst); saved_paths.append(dst)
            if not saved_paths: return _json_error("No valid files to add")
            result = add_files_to_index(root, dept, saved_paths)
            rows = list_index_sources(root, dept)
            return jsonify({"ok": True, "root": root, "dept": dept, "added": len(saved_paths),
                            "added_chunks": int(result.get("added_chunks", 0)),
                            "after": [{"source": s, "chunks": n} for s, n in rows]})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # JSON: {"paths":[...]}
    if request.is_json and request.json:
        paths = request.json.get("paths") or []
        if not isinstance(paths, list) or not paths:
            return _json_error("JSON body requires 'paths': [ ... ]")
        for p in paths:
            if not _allowed_file(p): 
                return _json_error(f"Unsupported: {p}. Allowed: {', '.join(sorted(ALLOWED_EXTS))}")
            if not os.path.isfile(p): 
                return _json_error(f"Not a file: {p}")
        result = add_files_to_index(root, dept, paths)
        rows = list_index_sources(root, dept)
        return jsonify({"ok": True, "root": root, "dept": dept, "added": len(paths),
                        "added_chunks": int(result.get("added_chunks", 0)),
                        "after": [{"source": s, "chunks": n} for s, n in rows]})

    return _json_error("Send multipart 'files' or JSON {'paths': [...]}")

@indexing_bp.post("/delete")
@login_required(api=True)
def delete_api():
    root = _get_root()
    if not request.is_json or not request.json:
        return _json_error("JSON body required")

    dept = request.json.get("dept")
    sources = request.json.get("sources")
    if not dept:
        return _json_error("Missing 'dept'")
    if not sources or not isinstance(sources, list):
        return _json_error("Missing 'sources' (array)")

    result = delete_sources_from_index(root, dept, sources)
    rows = list_index_sources(root, dept)
    return jsonify({
        "ok": True,
        "root": str(root),
        "dept": dept,
        "deleted_chunks": int(result.get("deleted_chunks", 0)),
        "rebuild": int(result.get("rebuild", 0)),
        "moved_files": int(result.get("moved_files", 0)),              # <— thêm
        "trash_dir": result.get("trash_dir"),                           # <— thêm
        "after": [{"source": s, "chunks": n} for s, n in rows]
    })
