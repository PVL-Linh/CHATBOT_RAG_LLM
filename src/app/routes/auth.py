# from flask import Blueprint, render_template, request, session, redirect, url_for
# from werkzeug.security import check_password_hash
# from app.Login.login_required import get_user

# bp = Blueprint('auth', __name__)

# @bp.route("/login", methods=["GET", "POST"])
# def login():
#     if request.method == "GET":
#         if session.get('user'):
#             return redirect(url_for('pages.chat'))
#         next_url = request.args.get("next", "")
#         return render_template("login/login.html", next_url=next_url)

#     # --- POST ---
#     username = (request.form.get("username") or "").strip()
#     password = (request.form.get("password") or "").strip()
#     remember = (request.form.get("remember") == "on")

#     # Lấy user từ SQLite
#     user = get_user(username)

#     if (not user) or (not password):
#         return render_template(
#             "login/login.html",
#             error="Tên đăng nhập hoặc mật khẩu không đúng.",
#             next_url=request.form.get("next", "")
#         )

#     stored_hash = user.get("password_hash") or ""

#     ok = False
#     try:
#         ok = check_password_hash(stored_hash, password)
#     except Exception:
#         ok = False

#     if not ok:
#         return render_template(
#             "login/login.html",
#             error="Tên đăng nhập hoặc mật khẩu không đúng.",
#             next_url=request.form.get("next", "")
#         )

#     # Đăng nhập thành công
#     session.clear()
#     session.permanent = remember
#     session['user'] = username
#     session['role'] = (user.get('role') or '').strip()
#     session['roles'] = user.get('roles', [])
#     session['messages'] = []

#     next_url = request.form.get("next") or request.args.get("next") or url_for("pages.chat")
#     return redirect(next_url)

# @bp.route("/logout")
# def logout():
#     session.clear()
#     return redirect(url_for("auth.login"))

# app/Login/auth.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from flask import Blueprint, flash, render_template, request, session, redirect, url_for

# Lấy user thật từ Supabase / DB qua helper đã viết
from app.Login.login_required import get_user

bp = Blueprint('auth', __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    # ---------- GET: hiện form ----------
    if request.method == "GET":
        if session.get('user'):
            return redirect(url_for('pages.chat'))
        next_url = request.args.get("next", "")
        return render_template("login/login.html", next_url=next_url)

    # ---------- POST: xử lý login ----------
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    remember = (request.form.get("remember") == "on")

    # Lấy user từ hệ thống thật (Supabase / DB)
    user = get_user(username)

    if (not user) or (not password):
        return render_template(
            "login/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            next_url=request.form.get("next", "")
        )

    # 🔴 CHỈ cho HOAT_DONG, mọi trạng thái khác đều chặn
    norm_status = (user.get("status") or "").upper()
    print(f"[auth.login] user={username}, status={norm_status}")        

    if norm_status != "HOAT_DONG":
        return render_template(
            "login/login.html",
            error="Tài khoản của bạn không ở trạng thái HOẠT ĐỘNG. Vui lòng liên hệ quản trị viên Tiximax.",
            next_url=request.form.get("next", "")
        )

    # 🔴 Password plain – so sánh trực tiếp
    stored_pass = (user.get("password") or "").strip()

    if password != stored_pass:
        return render_template(
            "login/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            next_url=request.form.get("next", "")
        )

    # ✅ Đăng nhập thành công (phần set session giữ nguyên như trước)
    session.clear()
    session.permanent = remember
    session['user'] = user.get("username") or username
    session['role'] = (user.get('role') or '').strip()
    session['roles'] = user.get('roles', [])
    session['messages'] = []
    staff_id = user.get("staff_id") or user.get("account_id") or user.get("id") or username
    session['staff_id'] = staff_id
    session['user_id'] = staff_id

    # Thay vì redirect thẳng về chat → đi qua trang trung gian để phá history
    return redirect(url_for('pages.post_login'))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
