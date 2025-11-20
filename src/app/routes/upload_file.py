import os
import time
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, session

bp = Blueprint("upload_file", __name__)

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/tiximax_uploads")


def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


@bp.route("/api/upload", methods=["POST"])
def upload_file():
    """
    Upload 1 file để dùng cho Q&A trong phiên (doc_qa).
    File sẽ KHÔNG tự động đưa vào RAG/DB, chỉ dùng tạm trong session.
    """
    if "file" not in request.files:
        return jsonify({"error": "Missing file"}), 400

    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    filename = secure_filename(f.filename)
    if not _allowed_file(filename):
        return jsonify({
            "error": "File type not allowed",
            "allowed": list(ALLOWED_EXTENSIONS),
        }), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, f"{int(time.time())}_{filename}")
    f.save(save_path)

    session["uploaded_file"] = save_path
    return jsonify({
        "ok": True,
        "message": "Đã tải file lên. Bạn có thể hỏi nội dung trong file này.",
        "file": filename,
        "path": save_path,
    })
