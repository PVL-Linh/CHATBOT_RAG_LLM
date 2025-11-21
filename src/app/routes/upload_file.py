from __future__ import annotations
import os
import time
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, session
from app.config.paths import UPLOAD_DIR

bp = Blueprint("upload_file", __name__)

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _get_user_upload_dir() -> str:
    """
    Tạo/tham chiếu thư mục upload riêng cho từng user.

    Ưu tiên:
    - session["user"] nếu có (ví dụ: username / email / id)
    - fallback: "anonymous"
    """
    raw_user = session.get("user") or "anonymous"
    safe_user = secure_filename(str(raw_user)) or "anonymous"

    user_dir = os.path.join(UPLOAD_DIR, safe_user)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


@bp.route("/api/upload", methods=["POST"])
def upload_file():
    """
    Upload 1 hoặc nhiều file để dùng cho Q&A trong phiên (doc_qa).
    File sẽ KHÔNG tự động đưa vào RAG/DB, chỉ dùng tạm trong session.
    - Form field: "file" (có thể nhiều file, dùng input multiple)
    - Mỗi user sẽ có thư mục riêng: UPLOAD_DIR/<user_sanitized>/
    """
    files = request.files.getlist("file")
    if not files:
        return jsonify({"error": "Missing file"}), 400

    saved_files = []
    errors = []

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    user_dir = _get_user_upload_dir()

    for f in files:
        if not f or not f.filename:
            errors.append({"filename": None, "error": "Empty filename"})
            continue

        filename = secure_filename(f.filename)

        if not _allowed_file(filename):
            errors.append({
                "filename": filename,
                "error": "File type not allowed",
                "allowed": list(ALLOWED_EXTENSIONS),
            })
            continue

        ts = int(time.time() * 1000)
        save_name = f"{ts}_{filename}"
        save_path = os.path.join(user_dir, save_name)
        f.save(save_path)

        saved_files.append({
            "name": filename,
            "stored_name": save_name,
            "path": save_path,
        })

    if not saved_files:
        return jsonify({
            "ok": False,
            "message": "Không có file hợp lệ được upload",
            "errors": errors,
        }), 400

    existing = session.get("uploaded_files", [])
    if not isinstance(existing, list):
        existing = []
    existing.extend(saved_files)
    session["uploaded_files"] = existing

    return jsonify({
        "ok": True,
        "message": "Đã tải file lên. Bạn có thể hỏi nội dung trong các file này.",
        "files": saved_files,
        "errors": errors,
    })
