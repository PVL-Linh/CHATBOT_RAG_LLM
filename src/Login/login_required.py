# import os, csv
# from werkzeug.security import generate_password_hash
# from functools import wraps
# from flask import request, session, redirect, url_for, jsonify

# USERS_CSV = os.environ.get("USERS_CSV", "./src/users.csv")
# ALLOWED_ROLES = {"marketing", "sales", "hr", "admin"}

# def load_users():
#     """Đọc users.csv, hỗ trợ password hoặc password_hash, kèm role."""
#     users = {}
#     if not os.path.exists(USERS_CSV):
#         return users
#     with open(USERS_CSV, newline='', encoding='utf-8') as f:
#         reader = csv.DictReader(f)
#         for row in reader:
#             u  = (row.get('username') or '').strip()
#             ph = (row.get('password_hash') or '').strip()
#             pw = (row.get('password') or '').strip()
#             role = (row.get('role') or 'marketing').strip().lower()
#             if not u:
#                 continue
#             if role not in ALLOWED_ROLES:
#                 role = 'marketing'
#             if ph:
#                 users[u] = {'password_hash': ph, 'role': role}
#             elif pw:
#                 users[u] = {'password_hash': generate_password_hash(pw), 'role': role}
#     return users

# def login_required(view=None, *, api=False, roles=None):
#     """
#     - Nếu roles=None: chỉ yêu cầu đăng nhập.
#     - Nếu roles=['marketing'] (vd): chỉ role đó (hoặc admin) được vào.
#     - api=True: trả JSON 401/403 thay vì redirect.
#     """
#     need_roles = set(roles or [])

#     def deco(fn):
#         @wraps(fn)
#         def wrapped(*args, **kwargs):
#             if not session.get('user'):
#                 if api:
#                     return jsonify({"error": "Unauthorized"}), 401
#                 return redirect(url_for('login', next=request.path))

#             if need_roles:
#                 role = (session.get('role') or '').lower()
#                 if role != 'admin' and role not in need_roles:
#                     if api:
#                         return jsonify({"error": "Forbidden", "allowed_roles": list(need_roles)}), 403
#                     # Khóa truy cập trang, đưa về Chat (trang luôn mở)
#                     return redirect(url_for('chat'))

#             return fn(*args, **kwargs)
#         return wrapped
#     return deco(view) if view else deco



# Login/login_required.py
import os, csv, re
from werkzeug.security import generate_password_hash
from functools import wraps
from flask import request, session, redirect, url_for, jsonify

USERS_CSV = os.environ.get("USERS_CSV", "./src/users.csv")
ALLOWED_ROLES = {"marketing", "manager_marketing", "sales", "hr", "admin"}


def _split_roles(val):
    """Chuẩn hoá role: nhận str/list, tách bởi , ; | / hoặc khoảng trắng -> list lowercase."""
    import re
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip().lower() for x in val if str(x).strip()]
    raw = str(val or "")
    toks = re.split(r"[,\s;|/]+", raw)
    return [t.strip().lower() for t in toks if t.strip()]

def _normalize_role_token(tok: str) -> str:
    t = (tok or "").strip().lower().replace("-", "_")
    if t in {"managermarketing", "manager_marketing", "manager marketing"}:
        return "manager_marketing"
    return t

def load_users():
    import csv, os
    from werkzeug.security import generate_password_hash

    users = {}
    if not os.path.exists(USERS_CSV):
        return users

    with open(USERS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            u  = (row.get('username') or '').strip()
            ph = (row.get('password_hash') or '').strip()
            pw = (row.get('password') or '').strip()
            role_raw = (row.get('role') or '').strip()
            if not u:
                continue

            # === Chuẩn hoá role (đã có ở bạn, nhắc lại cho đầy đủ) ===
            def _split_roles(val):
                import re
                if val is None: return []
                if isinstance(val, (list, tuple, set)):
                    return [str(x).strip().lower() for x in val if str(x).strip()]
                toks = re.split(r"[,\s;|/]+", str(val))
                return [t.strip().lower() for t in toks if t.strip()]

            def _normalize_role_token(tok: str) -> str:
                t = (tok or "").strip().lower().replace("-", "_")
                if t in {"managermarketing", "manager_marketing", "manager marketing"}:
                    return "manager_marketing"
                return t

            tokens = [_normalize_role_token(x) for x in _split_roles(role_raw)]
            roles  = [r for r in tokens if r in ALLOWED_ROLES]
            primary_role = roles[0] if roles else ''

            # === Tạo hash nếu chưa có, nhưng vẫn giữ plain để fallback ===
            if not ph and pw:
                ph = generate_password_hash(pw)

            users[u] = {
                'password_hash': ph,        # có thể là hash
                'password_plain': pw,       # giữ lại plain để tương thích
                'role': primary_role,
                'roles': roles
            }
    return users


def _normalize_required(roles):
    return set(_split_roles(roles)) if roles else set()

def _get_session_roles():
    """Hợp nhất cả 'role' (string) và 'roles' (list) trong session."""
    have = set(_split_roles(session.get('role')))
    have |= set(_split_roles(session.get('roles', [])))
    return have

def login_required(view=None, *, api=False, roles=None):
    """
    - Nếu roles=None: chỉ yêu cầu đăng nhập.
    - Nếu roles=['marketing'] (vd): chỉ role đó hoặc 'admin' được vào.
    - api=True: trả JSON 401/403 thay vì redirect.
    """
    need = _normalize_required(roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            # Chưa đăng nhập
            if not session.get('user'):
                if api:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for('auth.login', next=request.path))

            # Kiểm tra quyền
            if need:
                have = _get_session_roles()
                if not (have & (need | {'admin'})):  # admin có mọi quyền
                    if api:
                        return jsonify({
                            "error": "Forbidden",
                            "required_roles": sorted(list(need)),
                            "actual_roles":   sorted(list(have))
                        }), 403
                    # hoặc render 403.html tuỳ bạn
                    return redirect(url_for('chat'))

            return fn(*args, **kwargs)
        return wrapped
    return deco(view) if view else deco
