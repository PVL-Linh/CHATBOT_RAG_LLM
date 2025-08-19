import os, csv
from werkzeug.security import generate_password_hash
from functools import wraps
from flask import request, session, redirect, url_for, jsonify

USERS_CSV = os.environ.get("USERS_CSV", "./src/users.csv")
ALLOWED_ROLES = {"marketing", "sales", "hr", "admin"}

def load_users():
    """Đọc users.csv, hỗ trợ password hoặc password_hash, kèm role."""
    users = {}
    if not os.path.exists(USERS_CSV):
        return users
    with open(USERS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            u  = (row.get('username') or '').strip()
            ph = (row.get('password_hash') or '').strip()
            pw = (row.get('password') or '').strip()
            role = (row.get('role') or 'marketing').strip().lower()
            if not u:
                continue
            if role not in ALLOWED_ROLES:
                role = 'marketing'
            if ph:
                users[u] = {'password_hash': ph, 'role': role}
            elif pw:
                users[u] = {'password_hash': generate_password_hash(pw), 'role': role}
    return users

def login_required(view=None, *, api=False, roles=None):
    """
    - Nếu roles=None: chỉ yêu cầu đăng nhập.
    - Nếu roles=['marketing'] (vd): chỉ role đó (hoặc admin) được vào.
    - api=True: trả JSON 401/403 thay vì redirect.
    """
    need_roles = set(roles or [])

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user'):
                if api:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for('login', next=request.path))

            if need_roles:
                role = (session.get('role') or '').lower()
                if role != 'admin' and role not in need_roles:
                    if api:
                        return jsonify({"error": "Forbidden", "allowed_roles": list(need_roles)}), 403
                    # Khóa truy cập trang, đưa về Chat (trang luôn mở)
                    return redirect(url_for('chat'))

            return fn(*args, **kwargs)
        return wrapped
    return deco(view) if view else deco
