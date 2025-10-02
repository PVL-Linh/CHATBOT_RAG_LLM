# from flask import Blueprint, render_template, request, session, redirect, url_for
# from werkzeug.security import check_password_hash
# from app.Login.login_required import load_users

# bp = Blueprint('auth', __name__)
# @bp.route("/login", methods=["GET", "POST"])
# def login():
#     if request.method == "GET":
#         if session.get('user'):
#             return redirect(url_for('pages.chat'))
#         next_url = request.args.get("next", "")
#         return render_template("login/login.html", next_url=next_url)


#     username = (request.form.get("username") or "").strip()
#     password = (request.form.get("password") or "").strip()
#     remember = request.form.get("remember") == "on"


#     USERS = load_users()
#     user = USERS.get(username)


#     def _is_hashed(s: str) -> bool:
#         s = s or ""
#         return s.startswith(("pbkdf2:", "scrypt:", "argon2:", "bcrypt:"))
    
#     if (not user) or (not password):
#         return render_template("login/login.html", error="Tên đăng nhập hoặc mật khẩu không đúng.", next_url=request.form.get("next",""))


#     stored_hash = user.get("password_hash") or ""
#     stored_plain = user.get("password_plain") or ""


#     ok = False
#     try:
#         if _is_hashed(stored_hash):
#             ok = check_password_hash(stored_hash, password)
#         else:
#             ok = (password == stored_plain) or (password == stored_hash)
#     except Exception:
#         ok = (password == stored_plain)

#     if not ok:
#         return render_template("login/login.html", error="Tên đăng nhập hoặc mật khẩu không đúng.", next_url=request.form.get("next",""))
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



# app/Auth/views.py (ví dụ)
from flask import Blueprint, render_template, request, session, redirect, url_for
from werkzeug.security import check_password_hash
from app.Login.login_required import get_user

bp = Blueprint('auth', __name__)

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get('user'):
            return redirect(url_for('pages.chat'))
        next_url = request.args.get("next", "")
        return render_template("login/login.html", next_url=next_url)

    # --- POST ---
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    remember = (request.form.get("remember") == "on")

    # Lấy user từ SQLite
    user = get_user(username)

    if (not user) or (not password):
        return render_template(
            "login/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            next_url=request.form.get("next", "")
        )

    stored_hash = user.get("password_hash") or ""

    ok = False
    try:
        ok = check_password_hash(stored_hash, password)
    except Exception:
        ok = False

    if not ok:
        return render_template(
            "login/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            next_url=request.form.get("next", "")
        )

    # Đăng nhập thành công
    session.clear()
    session.permanent = remember
    session['user'] = username
    session['role'] = (user.get('role') or '').strip()
    session['roles'] = user.get('roles', [])
    session['messages'] = []

    next_url = request.form.get("next") or request.args.get("next") or url_for("pages.chat")
    return redirect(next_url)

@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
