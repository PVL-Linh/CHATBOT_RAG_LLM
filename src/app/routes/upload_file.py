from __future__ import annotations

import os
import time
from typing import List, Dict, Any

from flask import Blueprint, request, jsonify, session
from werkzeug.utils import secure_filename

from app.Login.login_required import login_required
from app.config.paths import UPLOAD_DIR

bp = Blueprint("upload_file", __name__)

# Các loại file cho phép upload
ALLOWED_EXTENSIONS = {
    ".txt", ".pdf", ".docx",        # văn bản
    ".jpg", ".jpeg", ".png",        # ảnh phổ biến
    ".gif", ".bmp", ".tiff", ".webp",
}

# Nhóm riêng extension ảnh để phân loại
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
}


def _allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _get_file_type(filename: str) -> str:
    """
    Phân loại file:
    - "image": các định dạng ảnh (jpg, png, webp, ...)
    - "doc"  : txt, pdf, docx, ...
    Dùng để branch luồng xử lý (OCR vs đọc text) ở phía RAG.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "doc"


def _get_user_upload_dir() -> str:
    """
    Thư mục upload riêng theo user (dựa trên session["user"]).
    Ví dụ: uploads/<username>/
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

    VERSION MỚI:
    - Mỗi lần upload batch mới → thay thế toàn bộ session["uploaded_files"]
      bằng batch mới đó (KHÔNG cộng dồn với batch cũ).
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

        # Đổi tên file để tránh trùng: <timestamp>_<tên gốc>
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

        file_type = _get_file_type(filename)

        saved_files.append(
            {
                "name": filename,          # tên hiển thị cho user
                "stored_name": stored_name,  # tên thực trên ổ đĩa
                "path": save_path,         # path tuyệt đối
                "file_type": file_type,    # 🔥 phân biệt image/doc cho RAG
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

    # 🔥 Quan trọng: ghi đè toàn bộ batch file cho phiên hiện tại
    session["uploaded_files"] = saved_files
    session["session_docs_dirty"] = True

    print(f"[UPLOAD] saved_files={saved_files}")  # debug

    return jsonify(
        {
            "ok": True,
            "message": "Đã tải file lên. Bạn có thể hỏi nội dung, hệ thống sẽ dùng các tài liệu này làm context.",
            "files": saved_files,
            "errors": errors,
        }
    )




# from __future__ import annotations

# import os
# import time
# from typing import List, Dict, Any
# from flask import Blueprint, request, jsonify, session
# from werkzeug.utils import secure_filename
# from app.Login.login_required import login_required
# from app.config.paths import UPLOAD_DIR

# bp = Blueprint("upload_file", __name__)

# # Thêm extension cho file văn bản (nếu bạn muốn thêm .jpg, .png thì mở rộng ở đây)
# ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx", ".jpg", ".jpeg", ".png"}


# def _allowed_file(filename: str) -> bool:
#     ext = os.path.splitext(filename)[1].lower()
#     return ext in ALLOWED_EXTENSIONS


# def _get_user_upload_dir() -> str:
#     """
#     Thư mục upload riêng theo user (dựa trên session["user"]).
#     Ví dụ: uploads/<username>/
#     """
#     raw_user = session.get("user") or "anonymous"
#     safe_user = secure_filename(str(raw_user)) or "anonymous"

#     user_dir = os.path.join(UPLOAD_DIR, safe_user)
#     os.makedirs(user_dir, exist_ok=True)
#     return user_dir


# @bp.route("/api/upload", methods=["POST"])
# @login_required(api=True)
# def upload_file():
#     """
#     Upload 1 hoặc nhiều file để dùng làm context RAG trong phiên (session_doc_vs).
#     - Form field: "file" (input multiple)
#     - Lưu metadata vào session["uploaded_files"] để:
#       + hiển thị lại cho user
#       + dùng để build FAISS mini theo session

#     VERSION MỚI:
#     - Mỗi lần upload batch mới → thay thế toàn bộ session["uploaded_files"]
#       bằng batch mới đó (KHÔNG cộng dồn với batch cũ).
#     """
#     files = request.files.getlist("file")
#     if not files:
#         return jsonify({"ok": False, "error": "Missing file"}), 400

#     os.makedirs(UPLOAD_DIR, exist_ok=True)
#     user_dir = _get_user_upload_dir()

#     saved_files: List[Dict[str, Any]] = []
#     errors: List[Dict[str, Any]] = []

#     for f in files:
#         if not f or not f.filename:
#             errors.append({"filename": None, "error": "Empty filename"})
#             continue

#         filename = secure_filename(f.filename)
#         if not _allowed_file(filename):
#             errors.append(
#                 {
#                     "filename": filename,
#                     "error": "File type not allowed",
#                     "allowed": list(ALLOWED_EXTENSIONS),
#                 }
#             )
#             continue

#         # Đổi tên file để tránh trùng: <timestamp>_<tên gốc>
#         ts = int(time.time() * 1000)
#         stored_name = f"{ts}_{filename}"
#         save_path = os.path.join(user_dir, stored_name)

#         try:
#             f.save(save_path)
#         except Exception as e:
#             errors.append(
#                 {
#                     "filename": filename,
#                     "error": f"Failed to save file: {e}",
#                 }
#             )
#             continue

#         saved_files.append(
#             {
#                 "name": filename,        # tên hiển thị cho user
#                 "stored_name": stored_name,  # tên thực trên ổ đĩa
#                 "path": save_path,       # path tuyệt đối
#             }
#         )

#     if not saved_files:
#         return (
#             jsonify(
#                 {
#                     "ok": False,
#                     "message": "Không có file hợp lệ được upload",
#                     "errors": errors,
#                 }
#             ),
#             400,
#         )
#     session["uploaded_files"] = saved_files
#     session["session_docs_dirty"] = True

#     return jsonify(
#         {
#             "ok": True,
#             "message": "Đã tải file lên. Bạn có thể hỏi nội dung, hệ thống sẽ dùng các tài liệu này làm context.",
#             "files": saved_files,
#             "errors": errors,
#         }
#     )
