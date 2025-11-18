# from __future__ import annotations
# import os
# import re
# import sqlite3
# import threading
# from typing import Dict, Any, List, Optional, Set, Iterable
# from werkzeug.security import generate_password_hash
# from app.config.paths import USERS_DB
# from fastapi import Request, Depends, HTTPException, status
# from pydantic import BaseModel

# DB_PATH = USERS_DB

# ALLOWED_ROLES: Set[str] = {
#     "marketing",
#     "manager_marketing",
#     "sales",
#     "hr",
#     "admin",
#     "manager_sales",
# }

# _ROLE_SPLIT_RE = re.compile(r"[,\s;|/]+")
# _DB_READY = False
# _DB_LOCK = threading.Lock()


# # ================== Helpers roles ==================

# def _split_roles(val: Any) -> List[str]:
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


# def _normalize_required(roles: Optional[Iterable[str] | str]) -> Set[str]:
#     return set(_split_roles(roles)) if roles else set()


# # ================== SQLite init ==================

# def _ensure_db() -> None:
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


# def _conn() -> sqlite3.Connection:
#     _ensure_db()
#     return sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)


# # ================== User CRUD ==================

# def get_user(username: str) -> Optional[Dict[str, Any]]:
#     """Trả dict: {password_hash, roles: [..], role: '...'} hoặc None."""
#     if not username:
#         return None
#     con = _conn()
#     con.row_factory = sqlite3.Row
#     try:
#         row = con.execute(
#             "SELECT username, password_hash, roles FROM users WHERE username=? LIMIT 1",
#             (username.strip(),),
#         ).fetchone()
#         if not row:
#             return None
#         roles = [r for r in (row["roles"] or "").split(",") if r]
#         return {
#             "password_hash": row["password_hash"],
#             "roles": roles,
#             "role": roles[0] if roles else "",
#         }
#     finally:
#         con.close()


# def upsert_user(
#     username: str,
#     *,
#     password: Optional[str] = None,
#     password_hash: Optional[str] = None,
#     roles: Any = None,
# ) -> None:
#     """
#     Tạo/sửa user. BẮT BUỘC có password hoặc password_hash.
#     roles có thể là string "a,b" hoặc list [...]. Chỉ nhận các role trong ALLOWED_ROLES.
#     """
#     if not username:
#         raise ValueError("username required")

#     tokens = [_normalize_role_token(x) for x in _split_roles(roles)]
#     tokens = [r for r in tokens if r in ALLOWED_ROLES]

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
#             (username.strip(), ph, roles_str),
#         )
#         con.commit()
#     finally:
#         con.close()


# def set_roles(username: str, roles: Any) -> None:
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
#         con.execute(
#             "UPDATE users SET roles=? WHERE username=?",
#             (roles_str, username.strip()),
#         )
#         con.commit()
#     finally:
#         con.close()


# def list_users() -> List[Dict[str, Any]]:
#     """Trả list[ {username, roles:[...], role} ]"""
#     con = _conn()
#     con.row_factory = sqlite3.Row
#     try:
#         rows = con.execute("SELECT username, roles FROM users ORDER BY username").fetchall()
#         out: List[Dict[str, Any]] = []
#         for r in rows:
#             roles = [x for x in (r["roles"] or "").split(",") if x]
#             out.append(
#                 {
#                     "username": r["username"],
#                     "roles": roles,
#                     "role": roles[0] if roles else "",
#                 }
#             )
#         return out
#     finally:
#         con.close()


# def delete_user(username: str) -> None:
#     con = _conn()
#     try:
#         con.execute("DELETE FROM users WHERE username=?", (username.strip(),))
#         con.commit()
#     finally:
#         con.close()


# def load_users() -> Dict[str, Dict[str, Any]]:
#     """Load tất cả users -> dict[username] = {...} (debug/admin)."""
#     users: Dict[str, Dict[str, Any]] = {}
#     con = _conn()
#     con.row_factory = sqlite3.Row
#     try:
#         rows = con.execute(
#             "SELECT username, password_hash, roles FROM users"
#         ).fetchall()
#         for r in rows:
#             roles = [x for x in (r["roles"] or "").split(",") if x]
#             users[r["username"]] = {
#                 "password_hash": r["password_hash"],
#                 "password_plain": "",
#                 "role": roles[0] if roles else "",
#                 "roles": roles,
#             }
#         return users
#     finally:
#         con.close()


# # ================== FastAPI deps ==================

# class AuthUser(BaseModel):
#     username: str
#     roles: List[str] = []
#     role: str = ""


# async def get_current_user_from_header(request: Request) -> AuthUser:
#     """
#     Đọc username từ header 'X-User-Id', tra DB, trả AuthUser.
#     Nếu không có hoặc không tồn tại user -> 401.
#     """
#     username = (request.headers.get("X-User-Id") or "").strip()
#     if not username:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Missing X-User-Id header",
#         )

#     info = get_user(username)
#     if not info:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Unknown user",
#         )

#     return AuthUser(
#         username=username,
#         roles=info.get("roles") or [],
#         role=info.get("role") or "",
#     )


# def require_user(roles: Optional[str | Iterable[str]] = None):
#     """
#     Dependency tương đương login_required(api=True, roles=...).

#     Dùng:
#         @router.get("/something")
#         async def some_api(user: AuthUser = Depends(require_user()))

#         @router.post("/marketing-only")
#         async def marketing_api(
#             user: AuthUser = Depends(require_user("marketing,manager_marketing")),
#         )
#     """
#     need = _normalize_required(roles)

#     async def dependency(user: AuthUser = Depends(get_current_user_from_header)) -> AuthUser:
#         if not need:
#             return user

#         have = {_normalize_role_token(x) for x in (user.roles or [])}
#         # admin luôn được phép
#         if not (have & (need | {"admin"})):
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail={
#                     "error": "Forbidden",
#                     "required_roles": sorted(list(need)),
#                     "actual_roles": sorted(list(have)),
#                 },
#             )
#         return user

#     return dependency


# # ================== Init / seed ==================

# def seed_admin_from_env() -> None:
#     """
#     Nếu muốn seed admin lần đầu:
#       ADMIN_USERNAME=admin
#       ADMIN_PASSWORD=...
#       ADMIN_ROLES=admin,manager_marketing
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


# def init_auth_storage() -> None:
#     """
#     Gọi trong create_app() (FastAPI).
#     """
#     _ensure_db()
#     seed_admin_from_env()
#     print(f"[auth_users_sqlite] DB ready at: {DB_PATH}")

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
#     return sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)


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


# src/app/Login/auth_users_sqlite.py
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import threading
from functools import wraps

from flask import request, session, redirect, url_for, jsonify
from werkzeug.security import generate_password_hash
from app.config.paths import USERS_DB

DB_PATH = USERS_DB

ALLOWED_ROLES = {
    "marketing", "manager_marketing", "sales", "hr", "admin", "manager_sales", "accountant"
}
_ROLE_SPLIT_RE = re.compile(r"[,\s;|/]+")
_DB_READY = False
_DB_LOCK = threading.Lock()


# ============================================================
# Helpers chuẩn hoá role
# ============================================================

def _split_roles(val):
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip().lower() for x in val if str(x).strip()]
    return [t.strip().lower() for t in _ROLE_SPLIT_RE.split(str(val or "")) if t.strip()]

def _normalize_role_token(tok: str) -> str:
    t = (tok or "").strip().lower().replace("-", "_")
    if t in {"managermarketing", "manager_marketing", "manager marketing"}:
        return "manager_marketing"
    if t in {"managersales", "manager_sales", "manager sales"}:
        return "manager_sales"
    if t == "sale":
        return "sales"
    return t


# ============================================================
# SQLite setup (WAL, table)
# ============================================================

def _ensure_db():
    """Tạo thư mục + bảng 'users' nếu chưa có."""
    global _DB_READY
    if _DB_READY:
        return
    with _DB_LOCK:
        if _DB_READY:
            return

        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        con = sqlite3.connect(DB_PATH, timeout=30)
        try:
            # Thiết lập WAL để giảm lock khi ghi
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute("PRAGMA busy_timeout=5000;")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS users(
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    roles TEXT DEFAULT ''  -- ví dụ: "marketing,hr"
                );
                """
            )
            con.commit()
            _DB_READY = True
        finally:
            con.close()

def _conn():
    _ensure_db()
    # check_same_thread=False để cho phép dùng connection ở các thread khác nhau
    return sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)


# ============================================================
# CRUD (GIỮ NGUYÊN API như mã cũ của bạn)
# ============================================================

def get_user(username: str):
    """Trả dict: {password_hash, roles: [..], role: '...'} hoặc None."""
    if not username:
        return None
    con = _conn()
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT username, password_hash, roles FROM users WHERE username=? LIMIT 1",
            (username.strip(),)
        ).fetchone()
        if not row:
            return None
        roles = [r for r in (row["roles"] or "").split(",") if r]
        return {
            "password_hash": row["password_hash"],
            "roles": roles,
            "role": roles[0] if roles else ""
        }
    finally:
        con.close()

def upsert_user(username: str, *, password: str = None, password_hash: str = None, roles=None):
    """
    Tạo/sửa user. BẮT BUỘC có password hoặc password_hash.
    roles có thể là string "a,b" hoặc list [...]. Chỉ nhận các role trong ALLOWED_ROLES.
    """
    if not username:
        raise ValueError("username required")

    tokens = [_normalize_role_token(x) for x in _split_roles(roles)]
    tokens = [r for r in tokens if r in ALLOWED_ROLES]

    # giữ thứ tự, loại trùng
    seen, norm_roles = set(), []
    for r in tokens:
        if r not in seen:
            seen.add(r)
            norm_roles.append(r)
    roles_str = ",".join(norm_roles)

    ph = password_hash or (generate_password_hash(password) if password else None)
    if not ph:
        raise ValueError("password or password_hash required")

    con = _conn()
    try:
        con.execute(
            "INSERT INTO users(username,password_hash,roles) VALUES(?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, roles=excluded.roles",
            (username.strip(), ph, roles_str)
        )
        con.commit()
    finally:
        con.close()

def set_roles(username: str, roles):
    tokens = [_normalize_role_token(x) for x in _split_roles(roles)]
    tokens = [r for r in tokens if r in ALLOWED_ROLES]
    seen, norm_roles = set(), []
    for r in tokens:
        if r not in seen:
            seen.add(r)
            norm_roles.append(r)
    roles_str = ",".join(norm_roles)
    con = _conn()
    try:
        con.execute("UPDATE users SET roles=? WHERE username=?", (roles_str, username.strip()))
        con.commit()
    finally:
        con.close()

def list_users():
    """Trả list[ {username, roles:[...], role} ]"""
    con = _conn()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT username, roles FROM users ORDER BY username").fetchall()
        out = []
        for r in rows:
            roles = [x for x in (r["roles"] or "").split(",") if x]
            out.append({
                "username": r["username"],
                "roles": roles,
                "role": roles[0] if roles else ""
            })
        return out
    finally:
        con.close()

def delete_user(username: str):
    con = _conn()
    try:
        con.execute("DELETE FROM users WHERE username=?", (username.strip(),))
        con.commit()
    finally:
        con.close()

def load_users():
    """
    GIỮ TƯƠNG THÍCH code cũ:
    Trả dict {username: {password_hash, password_plain:'', role, roles}}
    (password_plain để chuỗi rỗng vì không lưu plaintext trong SQLite)
    """
    users = {}
    con = _conn()
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT username, password_hash, roles FROM users").fetchall()
        for r in rows:
            roles = [x for x in (r["roles"] or "").split(",") if x]
            users[r["username"]] = {
                "password_hash": r["password_hash"],
                "password_plain": "",
                "role": roles[0] if roles else "",
                "roles": roles
            }
        return users
    finally:
        con.close()


# ============================================================
# Decorator login_required (y như bạn đang dùng)
# ============================================================

def _normalize_required(roles):
    return set(_split_roles(roles)) if roles else set()

def _get_session_roles():
    have = set()

    # role đơn
    have |= {_normalize_role_token(x) for x in _split_roles(session.get('role'))}

    # roles có thể là list hoặc string
    roles_val = session.get('roles', [])
    if isinstance(roles_val, (list, tuple, set)):
        have |= {_normalize_role_token(x) for x in roles_val}
    else:
        have |= {_normalize_role_token(x) for x in _split_roles(roles_val)}
    return have

def login_required(view=None, *, api=False, roles=None):
    """
    Dùng:
      @login_required
      @login_required(api=True)
      @login_required(roles="manager_marketing")
      @login_required(api=True, roles="marketing,manager_marketing")
    """
    need = _normalize_required(roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user'):
                if api:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for('auth.login', next=request.path))
            if need:
                have = _get_session_roles()
                if not (have & (need | {'admin'})):
                    if api:
                        return jsonify({
                            "error": "Forbidden",
                            "required_roles": sorted(list(need)),
                            "actual_roles":   sorted(list(have))
                        }), 403
                    return redirect(url_for('pages.chat'))
            return fn(*args, **kwargs)
        return wrapped

    return deco(view) if view else deco


# ============================================================
# Tuỳ chọn: init + seed (KHÔNG BẮT BUỘC GỌI)
# ============================================================

def seed_admin_from_env():
    """
    Nếu muốn seed admin lần đầu:
      set env: ADMIN_USERNAME=admin, ADMIN_PASSWORD=..., ADMIN_ROLES=admin,manager_marketing
    Không có ADMIN_PASSWORD thì không seed (tránh tạo user rỗng).
    """
    username = (os.getenv("ADMIN_USERNAME") or "admin").strip()
    password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    roles = os.getenv("ADMIN_ROLES") or "admin"
    if not password:
        return
    try:
        upsert_user(username, password=password, roles=roles)
    except Exception as e:
        print(f"[auth_users_sqlite] seed_admin_from_env warn: {e}")

def init_auth_storage():
    """
    Gọi tuỳ thích trong create_app() sau khi load env:
        from src.app.Login.auth_users_sqlite import init_auth_storage
        init_auth_storage()
    """
    _ensure_db()
    seed_admin_from_env()
    print(f"[auth_users_sqlite] DB ready at: {DB_PATH}")