# import os
# import re
# import sqlite3
# import threading
# from functools import wraps

# from flask import request, session, redirect, url_for, jsonify
# from werkzeug.security import generate_password_hash
# from app.config.paths import USERS_DB

# DB_PATH = USERS_DB

# ALLOWED_ROLES = {
#     "marketing", "manager_marketing", "sales", "hr", "admin", "manager_sales"
# }

# _ROLE_SPLIT_RE = re.compile(r"[,\s;|/]+")
# _DB_READY = False
# _DB_LOCK = threading.Lock()


# # ============================================================
# # Helpers chuẩn hoá role
# # ============================================================

# def _split_roles(val):
#     if val is None:
#         return []
#     if isinstance(val, (list, tuple, set)):
#         return [str(x).strip().lower() for x in val if str(x).strip()]
#     return [t.strip().lower() for t in _ROLE_SPLIT_RE.split(str(val or "")) if t.strip()]

# def _normalize_role_token(tok: str) -> str:
#     t = (tok or "").strip().lower().replace("-", "_")
#     if t in {"managermarketing", "manager_marketing", "manager marketing"}:
#         return "manager_marketing"
#     if t in {"managersales", "manager_sales", "manager sales"}:
#         return "manager_sales"
#     if t == "sale":
#         return "sales"
#     return t


# # ============================================================
# # SQLite setup (WAL, table)
# # ============================================================

# def _ensure_db():
#     """Tạo thư mục + bảng 'users' nếu chưa có."""
#     global _DB_READY
#     if _DB_READY:
#         return
#     with _DB_LOCK:
#         if _DB_READY:
#             return

#         os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
#         con = sqlite3.connect(DB_PATH, timeout=30)
#         try:
#             # Thiết lập WAL để giảm lock khi ghi
#             con.execute("PRAGMA journal_mode=WAL;")
#             con.execute("PRAGMA synchronous=NORMAL;")
#             con.execute("PRAGMA busy_timeout=5000;")
#             con.execute(
#                 """
#                 CREATE TABLE IF NOT EXISTS users(
#                     username TEXT PRIMARY KEY,
#                     password_hash TEXT NOT NULL,
#                     roles TEXT DEFAULT ''  -- ví dụ: "marketing,hr"
#                 );
#                 """
#             )
#             con.commit()
#             _DB_READY = True
#         finally:
#             con.close()

# def _conn():
#     _ensure_db()
#     # check_same_thread=False để cho phép dùng connection ở các thread khác nhau
#     return sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)


# # ============================================================
# # CRUD (GIỮ NGUYÊN API như mã cũ của bạn)
# # ============================================================

# def get_user(username: str):
#     """Trả dict: {password_hash, roles: [..], role: '...'} hoặc None."""
#     if not username:
#         return None
#     con = _conn()
#     con.row_factory = sqlite3.Row
#     try:
#         row = con.execute(
#             "SELECT username, password_hash, roles FROM users WHERE username=? LIMIT 1",
#             (username.strip(),)
#         ).fetchone()
#         if not row:
#             return None
#         roles = [r for r in (row["roles"] or "").split(",") if r]
#         return {
#             "password_hash": row["password_hash"],
#             "roles": roles,
#             "role": roles[0] if roles else ""
#         }
#     finally:
#         con.close()

# def upsert_user(username: str, *, password: str = None, password_hash: str = None, roles=None):
#     """
#     Tạo/sửa user. BẮT BUỘC có password hoặc password_hash.
#     roles có thể là string "a,b" hoặc list [...]. Chỉ nhận các role trong ALLOWED_ROLES.
#     """
#     if not username:
#         raise ValueError("username required")

#     tokens = [_normalize_role_token(x) for x in _split_roles(roles)]
#     tokens = [r for r in tokens if r in ALLOWED_ROLES]

#     # giữ thứ tự, loại trùng
#     seen, norm_roles = set(), []
#     for r in tokens:
#         if r not in seen:
#             seen.add(r)
#             norm_roles.append(r)
#     roles_str = ",".join(norm_roles)

#     ph = password_hash or (generate_password_hash(password) if password else None)
#     if not ph:
#         raise ValueError("password or password_hash required")

#     con = _conn()
#     try:
#         con.execute(
#             "INSERT INTO users(username,password_hash,roles) VALUES(?,?,?) "
#             "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, roles=excluded.roles",
#             (username.strip(), ph, roles_str)
#         )
#         con.commit()
#     finally:
#         con.close()

# def set_roles(username: str, roles):
#     tokens = [_normalize_role_token(x) for x in _split_roles(roles)]
#     tokens = [r for r in tokens if r in ALLOWED_ROLES]
#     seen, norm_roles = set(), []
#     for r in tokens:
#         if r not in seen:
#             seen.add(r)
#             norm_roles.append(r)
#     roles_str = ",".join(norm_roles)
#     con = _conn()
#     try:
#         con.execute("UPDATE users SET roles=? WHERE username=?", (roles_str, username.strip()))
#         con.commit()
#     finally:
#         con.close()

# def list_users():
#     """Trả list[ {username, roles:[...], role} ]"""
#     con = _conn()
#     con.row_factory = sqlite3.Row
#     try:
#         rows = con.execute("SELECT username, roles FROM users ORDER BY username").fetchall()
#         out = []
#         for r in rows:
#             roles = [x for x in (r["roles"] or "").split(",") if x]
#             out.append({
#                 "username": r["username"],
#                 "roles": roles,
#                 "role": roles[0] if roles else ""
#             })
#         return out
#     finally:
#         con.close()

# def delete_user(username: str):
#     con = _conn()
#     try:
#         con.execute("DELETE FROM users WHERE username=?", (username.strip(),))
#         con.commit()
#     finally:
#         con.close()

# def load_users():
#     """
#     GIỮ TƯƠNG THÍCH code cũ:
#     Trả dict {username: {password_hash, password_plain:'', role, roles}}
#     (password_plain để chuỗi rỗng vì không lưu plaintext trong SQLite)
#     """
#     users = {}
#     con = _conn()
#     con.row_factory = sqlite3.Row
#     try:
#         rows = con.execute("SELECT username, password_hash, roles FROM users").fetchall()
#         for r in rows:
#             roles = [x for x in (r["roles"] or "").split(",") if x]
#             users[r["username"]] = {
#                 "password_hash": r["password_hash"],
#                 "password_plain": "",
#                 "role": roles[0] if roles else "",
#                 "roles": roles
#             }
#         return users
#     finally:
#         con.close()


# # ============================================================
# # Decorator login_required (y như bạn đang dùng)
# # ============================================================

# def _normalize_required(roles):
#     return set(_split_roles(roles)) if roles else set()

# def _get_session_roles():
#     have = set()

#     # role đơn
#     have |= {_normalize_role_token(x) for x in _split_roles(session.get('role'))}

#     # roles có thể là list hoặc string
#     roles_val = session.get('roles', [])
#     if isinstance(roles_val, (list, tuple, set)):
#         have |= {_normalize_role_token(x) for x in roles_val}
#     else:
#         have |= {_normalize_role_token(x) for x in _split_roles(roles_val)}
#     return have

# def login_required(view=None, *, api=False, roles=None):
#     """
#     Dùng:
#       @login_required
#       @login_required(api=True)
#       @login_required(roles="manager_marketing")
#       @login_required(api=True, roles="marketing,manager_marketing")
#     """
#     need = _normalize_required(roles)

#     def deco(fn):
#         @wraps(fn)
#         def wrapped(*args, **kwargs):
#             if not session.get('user'):
#                 if api:
#                     return jsonify({"error": "Unauthorized"}), 401
#                 return redirect(url_for('auth.login', next=request.path))
#             if need:
#                 have = _get_session_roles()
#                 if not (have & (need | {'admin'})):
#                     if api:
#                         return jsonify({
#                             "error": "Forbidden",
#                             "required_roles": sorted(list(need)),
#                             "actual_roles":   sorted(list(have))
#                         }), 403
#                     return redirect(url_for('pages.chat'))
#             return fn(*args, **kwargs)
#         return wrapped

#     return deco(view) if view else deco


# # ============================================================
# # Tuỳ chọn: init + seed (KHÔNG BẮT BUỘC GỌI)
# # ============================================================

# def seed_admin_from_env():
#     """
#     Nếu muốn seed admin lần đầu:
#       set env: ADMIN_USERNAME=admin, ADMIN_PASSWORD=..., ADMIN_ROLES=admin,manager_marketing
#     Không có ADMIN_PASSWORD thì không seed (tránh tạo user rỗng).
#     """
#     username = (os.getenv("ADMIN_USERNAME") or "admin").strip()
#     password = (os.getenv("ADMIN_PASSWORD") or "").strip()
#     roles = os.getenv("ADMIN_ROLES") or "admin"
#     if not password:
#         return
#     try:
#         upsert_user(username, password=password, roles=roles)
#     except Exception as e:
#         print(f"[auth_users_sqlite] seed_admin_from_env warn: {e}")

# def init_auth_storage():
#     """
#     Gọi tuỳ thích trong create_app() sau khi load env:
#         from src.app.Login.auth_users_sqlite import init_auth_storage
#         init_auth_storage()
#     """
#     _ensure_db()
#     seed_admin_from_env()
#     print(f"[auth_users_sqlite] DB ready at: {DB_PATH}")







# app/Login/auth_users_sqlite.py
# -*- coding: utf-8 -*-
"""
Auth helper cho Tiximax – KHÔNG làm login/logout.

Giả định:
- Bảng tài khoản thật là `account` (Supabase API).
- Các cột chính:
    - account_id (int)
    - username   (str)
    - password   (str, plain text, KHÔNG hash)
    - role/roles (str hoặc list)  ví dụ: "sales", "manager_sales", "admin", ...
    - staff_id   (int)  (nếu có, để map sang nhân viên)

File này cung cấp:
- get_user(username)        -> lấy user từ bảng account thật
- ALLOWED_ROLES
- normalize_roles(raw)
- login_required(...)
- build_principal_from_session() -> cho db_router/chat.py
"""

from __future__ import annotations

import re
from functools import wraps
from typing import List, Set, Dict, Any, Optional

from flask import session, request, redirect, url_for, jsonify

try:
    from app.Model_LLM.Chat_Database.db_cli import fetch_table_all
except Exception:
    from app.Model_LLM.Chat_Database.db_cli import fetch_table_all

# ============================================================
# 1. Role hợp lệ + helper chuẩn hoá
# ============================================================

ALLOWED_ROLES = {
    "marketing",
    "manager_marketing",
    "sales",
    "hr",
    "admin",
    "manager_sales",
    "accountant",
    "warehouse",
}

_ROLE_SPLIT_RE = re.compile(r"[,\s;|/]+")


def _split_roles(val) -> List[str]:
    """Tách chuỗi role: 'a,b c;d' -> ['a','b','c','d'] (lower-case)."""
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip().lower() for x in val if str(x).strip()]
    return [
        t.strip().lower()
        for t in _ROLE_SPLIT_RE.split(str(val or ""))
        if t.strip()
    ]


def _normalize_role_token(tok: str) -> str:
    """Chuẩn hoá các biến thể 'manager sales' -> 'manager_sales', 'sale' -> 'sales'."""
    t = (tok or "").strip().lower().replace("-", "_")
    if t in {"managermarketing", "manager_marketing", "manager marketing"}:
        return "manager_marketing"
    if t in {"managersales", "manager_sales", "manager sales", "lead_sale"}:
        return "manager_sales"
    if t in {"sale", "staff_sale"}:
        return "sales"
    if t in {"accounting", "accountant"}:
        return "accountant"
    if t in {"warehouse", "staff_warehouse_foreign", "staff_warehouse_domestic"}:
        return "warehouse"
    if t in {"hr", "human_resources", "human resources"}:
        return "hr"
    return t.lower()


def normalize_roles(raw_roles) -> List[str]:
    """
    Chuẩn hoá role lấy từ DB hoặc user:
      - đầu vào: string ("sales, manager_sales") HOẶC list
      - đầu ra: list role hợp lệ, không trùng, đã normalize
    """
    tokens = [_normalize_role_token(x) for x in _split_roles(raw_roles)]
    tokens = [r for r in tokens if r in ALLOWED_ROLES or r == "admin"]
    seen: Set[str] = set()
    out: List[str] = []
    for r in tokens:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ============================================================
# 2. get_user: lấy user từ bảng account thật (API Supabase)
# ============================================================

def get_user(username: str) -> Optional[Dict[str, Any]]:
    """
    Lấy user thật từ bảng `account` qua API.

    Trả về dict chuẩn hoá:
      {
        "id": account_id or username,
        "username": str,
        "password": str (plain),
        "role": str (role chính),
        "roles": [list role đã normalize],
        "staff_id": staff_id or account_id or username,
        "account_id": account_id,
        "status": "HOAT_DONG" / "BI_KHOA" / ... (nếu có)
      }
    hoặc None nếu không tìm thấy.
    """
    username = (username or "").strip()
    if not username:
        return None

    try:
        rows = fetch_table_all(
            "account",
            params={"eq__username": username},
            page_size=5,
            max_pages=1,
        )
    except Exception as e:
        print(f"[auth_users_sqlite] Lỗi get_user gọi API account: {e}")
        return None

    if not rows:
        return None

    row = rows[0]

    # Password plain (sửa tên cột nếu DB khác)
    password_plain = (
        row.get("password")
        or row.get("password_plain")
        or ""
    )

    # Role / roles
    raw_roles = row.get("roles")
    if not raw_roles:
        raw_roles = row.get("role") or ""

    roles = normalize_roles(raw_roles)
    main_role = roles[0] if roles else ""

    account_id = row.get("account_id") or row.get("id") or None
    staff_id = row.get("staff_id") or account_id or username
    raw_status = (
        row.get("status")
        or row.get("trang_thai")
        or row.get("account_status")
        or row.get("state")
        or ""
    )
    status = raw_status.strip().upper().replace(" ", "_")

    return {
        "id": account_id or username,
        "username": row.get("username") or username,
        "password": str(password_plain),
        "role": main_role,
        "roles": roles,
        "staff_id": staff_id,
        "account_id": account_id,
        "status": status,
        "status_raw": raw_status,
        "_raw": row,
    }

# ============================================================
# 3. login_required decorator
# ============================================================

def _normalize_required(roles) -> Set[str]:
    return set(_split_roles(roles)) if roles else set()


def _get_session_roles() -> Set[str]:
    """
    Lấy full tập role hiện tại từ session:
        session["role"]  -> role chính
        session["roles"] -> list role
    """
    have: Set[str] = set()

    # role đơn
    have |= {_normalize_role_token(x) for x in _split_roles(session.get("role"))}

    # roles có thể là list hoặc string
    roles_val = session.get("roles", [])
    if isinstance(roles_val, (list, tuple, set)):
        have |= {_normalize_role_token(x) for x in roles_val}
    else:
        have |= {_normalize_role_token(x) for x in _split_roles(roles_val)}

    # chỉ giữ role hợp lệ
    have = {r for r in have if r in ALLOWED_ROLES or r == "admin"}
    return have


def login_required(view=None, *, api: bool = False, roles=None):
    """
    Dùng:
      @login_required
      @login_required(api=True)
      @login_required(roles="sales,manager_sales")

    - Nếu chưa có session["user"]:
        + api=True  -> trả JSON 401
        + api=False -> redirect tới 'auth.login'
    - Nếu có roles yêu cầu:
        + chỉ cho qua nếu (roles_session ∩ (roles_yêu_cầu ∪ {'admin'})) != ∅
    """
    need = _normalize_required(roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("user"):
                if api:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for("auth.login", next=request.path))

            if need:
                have = _get_session_roles()
                if not (have & (need | {"admin"})):
                    if api:
                        return jsonify({
                            "error": "Forbidden",
                            "required_roles": sorted(list(need)),
                            "actual_roles": sorted(list(have)),
                        }), 403
                    return redirect(url_for("pages.chat"))

            return fn(*args, **kwargs)

        return wrapped

    return deco(view) if view else deco


# ============================================================
# 4. build_principal_from_session – cho nhánh DB
# ============================================================

def build_principal_from_session() -> Dict[str, Any]:
    """
    Helper dùng trong chat.py / db_router:
        principal = build_principal_from_session()

    Trả về:
      {
        "id":        staff_id hoặc user_id,
        "username":  username,
        "role":      'ADMIN'/'MANAGER'/'SALE'/'OTHER',
        "raw_roles": [danh sách role chuẩn hoá],
      }
    """
    username = session.get("user") or ""
    staff_id = session.get("staff_id") or session.get("user_id")

    raw_roles = []

    r_single = session.get("role")
    if r_single:
        raw_roles.append(r_single)

    r_multi = session.get("roles", [])
    if isinstance(r_multi, (list, tuple, set)):
        raw_roles.extend(list(r_multi))
    else:
        raw_roles.extend(_split_roles(r_multi))

    norm = {_normalize_role_token(r) for r in raw_roles}

    # Map sang role logic cho DB
    if "admin" in norm:
        app_role = "ADMIN"
    elif "manager_sales" in norm or "manager_marketing" in norm:
        app_role = "LEAD_SALE"
    elif "sales" in norm:
        app_role = "STAFF_SALE"
    elif "accountant" in norm:
        app_role = "ACCOUNTANT"
    elif "hr" in norm:
        app_role = "HR"
    elif "warehouse" in norm:
        app_role = "WAREHOUSE"
    else:
        app_role = "OTHER"

    return {
        "id": staff_id,
        "username": username,
        "role": app_role,
        "raw_roles": sorted(list(norm)),
    }
