from __future__ import annotations

import bcrypt
from flask import Blueprint, render_template, request, session, redirect, url_for

# Lấy user từ DB (đã trả về password_hash)
from app.Login.login_required import get_user

bp = Blueprint('auth', __name__, template_folder='templates')


def verify_bcrypt_password(plain_password: str, hashed_password: str) -> bool:
    """Kiểm tra mật khẩu plain với hash BCrypt"""
    if not plain_password or not hashed_password:
        return False
    try:
        # hashed_password từ DB phải là chuỗi bắt đầu bằng $2a$, $2b$, $2y$...
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception as e:
        print(f"[bcrypt] Error verifying password: {e}")
        return False


@bp.route("/login", methods=["GET", "POST"])
def login():
    # Nếu đã login rồi → chuyển thẳng vào chat
    if session.get("user"):
        return redirect(url_for("pages.chat"))

    if request.method == "GET":
        next_url = request.args.get("next", "")
        return render_template("login/login.html", next_url=next_url)

    # ================== POST ==================
    username = (request.form.get("username") or "").strip()  # Giữ nguyên username, không .lower()
    password = request.form.get("password") or ""
    remember = request.form.get("remember") == "on"
    next_url = request.form.get("next") or url_for("pages.chat")

    if not username or not password:
        return render_template(
            "login/login.html",
            error="Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.",
            username=username,
            next_url=next_url
        ), 400

    # Lấy thông tin user từ DB
    user = get_user(username)

    if not user:
        print(f"[auth.login] Không tìm thấy user: {username}")
        return render_template(
            "login/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            username=username,
            next_url=next_url
        ), 401

    # Kiểm tra trạng thái tài khoản
    status = (user.get("status") or "").strip().upper()
    if status != "HOAT_DONG":
        print(f"[auth.login] Tài khoản {username} bị khóa hoặc không hoạt động: {status}")
        return render_template(
            "login/login.html",
            error="Tài khoản của bạn đã bị khóa hoặc chưa được kích hoạt. Vui lòng liên hệ quản trị viên.",
            username=username,
            next_url=next_url
        ), 403

    # Lấy password từ DB: ưu tiên hash, fallback plain (để bạn có thể dùng tài khoản 1/1 đơn giản)
    hashed_or_plain = user.get("password_hash") or user.get("password") or ""

    ok = False
    if hashed_or_plain.startswith("$2"):
        # BCrypt hash
        ok = verify_bcrypt_password(password, hashed_or_plain)
    else:
        # Plain text so sánh trực tiếp (phù hợp với tài khoản test như 1 / 1)
        ok = (password == hashed_or_plain)

    if not ok:
        print(f"[auth.login] Sai mật khẩu cho user: {username}")
        return render_template(
            "login/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            username=username,
            next_url=next_url
        ), 401

    session.clear()
    session.permanent = remember

    session["user"] = user["username"]
    session["role"] = user.get("role", "")
    session["roles"] = user.get("roles", [])
    session["staff_id"] = user.get("staff_id") or user.get("account_id") or user["username"]
    session["user_id"] = session["staff_id"]
    session["account_id"] = user.get("account_id")
    session["messages"] = []

    print(f"[auth.login] Đăng nhập thành công: {username} | Roles: {session['roles']}")

    return redirect(next_url)


@bp.route("/logout")
def logout():
    username = session.get("user", "unknown")
    session.clear()
    print(f"[auth.logout] User {username} đã đăng xuất")
    return redirect(url_for("auth.login"))