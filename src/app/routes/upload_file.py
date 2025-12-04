# app/routes/upload_file.py
from __future__ import annotations

import os
import time
from typing import List, Dict, Any
from flask import Blueprint, request, jsonify, session
from werkzeug.utils import secure_filename
from app.Login.login_required import login_required
from app.config.paths import UPLOAD_DIR

bp = Blueprint("upload_file", __name__)

# Thêm extension cho hình ảnh (jpg, jpeg, png, gif, bmp)
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx", ".jpg", ".jpeg", ".png", ".pages"}


def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _get_user_upload_dir() -> str:
    """
    Thư mục upload riêng theo user (dựa trên session["user"]).
    """
    raw_user = session.get("user") or "anonymous"
    safe_user = secure_filename(str(raw_user)) or "anonymous"

    user_dir = os.path.join(UPLOAD_DIR, safe_user)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


@bp.route("/api/upload", methods=["POST"])
@login_required(api=True)
def upload_file():
    """
    Upload 1 hoặc nhiều file để dùng làm context RAG trong phiên (session_doc_vs).
    - Form field: "file" (input multiple)
    - Lưu metadata vào session["uploaded_files"] để:
      + hiển thị lại cho user
      + dùng để build FAISS mini theo session
    """
    files = request.files.getlist("file")
    if not files:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    user_dir = _get_user_upload_dir()

    saved_files: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for f in files:
        if not f or not f.filename:
            errors.append({"filename": None, "error": "Empty filename"})
            continue

        filename = secure_filename(f.filename)
        if not _allowed_file(filename):
            errors.append(
                {
                    "filename": filename,
                    "error": "File type not allowed",
                    "allowed": list(ALLOWED_EXTENSIONS),
                }
            )
            continue

        ts = int(time.time() * 1000)
        stored_name = f"{ts}_{filename}"
        save_path = os.path.join(user_dir, stored_name)

        try:
            f.save(save_path)
        except Exception as e:
            errors.append(
                {
                    "filename": filename,
                    "error": f"Failed to save file: {e}",
                }
            )
            continue

        saved_files.append(
            {
                "name": filename,
                "stored_name": stored_name,
                "path": save_path,
            }
        )

    if not saved_files:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Không có file hợp lệ được upload",
                    "errors": errors,
                }
            ),
            400,
        )

    existing = session.get("uploaded_files", [])
    if not isinstance(existing, list):
        existing = []

    existing.extend(saved_files)
    session["uploaded_files"] = existing

    # Có thể dùng flag nếu muốn trigger build lại FAISS mini
    session["session_docs_dirty"] = True

    return jsonify(
        {
            "ok": True,
            "message": "Đã tải file lên. Bạn có thể hỏi nội dung, hệ thống sẽ dùng thêm tài liệu này làm context.",
            "files": saved_files,
            "errors": errors,
        }
    )