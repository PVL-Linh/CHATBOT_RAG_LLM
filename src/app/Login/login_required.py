# from __future__ import annotations

# import re
# from functools import wraps
# from typing import List, Set, Dict, Any, Optional

# from flask import session, request, redirect, url_for, jsonify

# try:
#     from app.Model_LLM.Chat_Database.db_cli import fetch_table_all
# except Exception:
#     from app.Model_LLM.Chat_Database.db_cli import fetch_table_all

# # ============================================================
# # 1. Role hợp lệ + helper chuẩn hoá
# # ============================================================

# ALLOWED_ROLES = {
#     "marketing",
#     "manager_marketing",
#     "sales",
#     "hr",
#     "admin",
#     "manager_sales",
#     "accountant",
#     "warehouse",
# }

# _ROLE_SPLIT_RE = re.compile(r"[,\s;|/]+")


# def _split_roles(val) -> List[str]:
#     """Tách chuỗi role: 'a,b c;d' -> ['a','b','c','d'] (lower-case)."""
#     if val is None:
#         return []
#     if isinstance(val, (list, tuple, set)):
#         return [str(x).strip().lower() for x in val if str(x).strip()]
#     return [
#         t.strip().lower()
#         for t in _ROLE_SPLIT_RE.split(str(val or ""))
#         if t.strip()
#     ]


# def _normalize_role_token(tok: str) -> str:
#     """Chuẩn hoá các biến thể 'manager sales' -> 'manager_sales', 'sale' -> 'sales'."""
#     t = (tok or "").strip().lower().replace("-", "_")
#     if t in {"managermarketing", "manager_marketing", "manager marketing"}:
#         return "manager_marketing"
#     if t in {"managersales", "manager_sales", "manager sales", "lead_sale"}:
#         return "manager_sales"
#     if t in {"sale", "staff_sale"}:
#         return "sales"
#     if t in {"accounting", "accountant"}:
#         return "accountant"
#     if t in {"hr", "human_resources", "human resources"}:
#         return "hr"
#     if t in {"staff_warehouse_domestic", "staff_warehouse_foreign"}:
#         return "warehouse"
#     return t.lower()


# def normalize_roles(raw_roles) -> List[str]:
#     """
#     Chuẩn hoá role lấy từ DB hoặc user:
#       - đầu vào: string ("sales, manager_sales") HOẶC list
#       - đầu ra: list role hợp lệ, không trùng, đã normalize
#     """
#     tokens = [_normalize_role_token(x) for x in _split_roles(raw_roles)]
#     tokens = [r for r in tokens if r in ALLOWED_ROLES or r == "admin"]
#     seen: Set[str] = set()
#     out: List[str] = []
#     for r in tokens:
#         if r not in seen:
#             seen.add(r)
#             out.append(r)
#     return out


# # ============================================================
# # 2. get_user: lấy user từ bảng account thật (API Supabase)
# # ============================================================

# def get_user(username: str) -> Optional[Dict[str, Any]]:
#     """
#     Lấy user thật từ bảng `account` qua API.

#     Trả về dict chuẩn hoá:
#       {
#         "id": account_id or username,
#         "username": str,
#         "password": str (plain),
#         "role": str (role chính),
#         "roles": [list role đã normalize],
#         "staff_id": staff_id or account_id or username,
#         "account_id": account_id,
#         "status": "HOAT_DONG" / "BI_KHOA" / ... (nếu có)
#       }
#     hoặc None nếu không tìm thấy.
#     """
#     username = (username or "").strip()
#     if not username:
#         return None

#     try:
#         rows = fetch_table_all(
#             "account",
#             params={"eq__username": username},
#             page_size=5,
#             max_pages=1,
#         )
#     except Exception as e:
#         print(f"[auth_users_sqlite] Lỗi get_user gọi API account: {e}")
#         return None

#     if not rows:
#         return None

#     row = rows[0]

#     # Password plain (sửa tên cột nếu DB khác)
#     password_plain = (
#         row.get("password")
#         or row.get("password_plain")
#         or ""
#     )

#     # Role / roles
#     raw_roles = row.get("roles")
#     if not raw_roles:
#         raw_roles = row.get("role") or ""

#     roles = normalize_roles(raw_roles)
#     main_role = roles[0] if roles else ""

#     account_id = row.get("account_id") or row.get("id") or None
#     staff_id = row.get("staff_id") or account_id or username
#     raw_status = (
#         row.get("status")
#         or row.get("trang_thai")
#         or row.get("account_status")
#         or row.get("state")
#         or ""
#     )
#     status = raw_status.strip().upper().replace(" ", "_")

#     return {
#         "id": account_id or username,
#         "username": row.get("username") or username,
#         "password": str(password_plain),
#         "role": main_role,
#         "roles": roles,
#         "staff_id": staff_id,
#         "account_id": account_id,
#         "status": status,
#         "status_raw": raw_status,
#         "_raw": row,
#     }

# # ============================================================
# # 3. login_required decorator
# # ============================================================

# def _normalize_required(roles) -> Set[str]:
#     return set(_split_roles(roles)) if roles else set()


# def _get_session_roles() -> Set[str]:
#     """
#     Lấy full tập role hiện tại từ session:
#         session["role"]  -> role chính
#         session["roles"] -> list role
#     """
#     have: Set[str] = set()

#     # role đơn
#     have |= {_normalize_role_token(x) for x in _split_roles(session.get("role"))}

#     # roles có thể là list hoặc string
#     roles_val = session.get("roles", [])
#     if isinstance(roles_val, (list, tuple, set)):
#         have |= {_normalize_role_token(x) for x in roles_val}
#     else:
#         have |= {_normalize_role_token(x) for x in _split_roles(roles_val)}

#     # chỉ giữ role hợp lệ
#     have = {r for r in have if r in ALLOWED_ROLES or r == "admin"}
#     return have


# def login_required(view=None, *, api: bool = False, roles=None):
#     """
#     Dùng:
#       @login_required
#       @login_required(api=True)
#       @login_required(roles="sales,manager_sales")

#     - Nếu chưa có session["user"]:
#         + api=True  -> trả JSON 401
#         + api=False -> redirect tới 'auth.login'
#     - Nếu có roles yêu cầu:
#         + chỉ cho qua nếu (roles_session ∩ (roles_yêu_cầu ∪ {'admin'})) != ∅
#     """
#     need = _normalize_required(roles)

#     def deco(fn):
#         @wraps(fn)
#         def wrapped(*args, **kwargs):
#             if not session.get("user"):
#                 if api:
#                     return jsonify({"error": "Unauthorized"}), 401
#                 return redirect(url_for("auth.login", next=request.path))

#             if need:
#                 have = _get_session_roles()
#                 if not (have & (need | {"admin"})):
#                     if api:
#                         return jsonify({
#                             "error": "Forbidden",
#                             "required_roles": sorted(list(need)),
#                             "actual_roles": sorted(list(have)),
#                         }), 403
#                     return redirect(url_for("pages.chat"))

#             return fn(*args, **kwargs)

#         return wrapped

#     return deco(view) if view else deco


# # ============================================================
# # 4. build_principal_from_session – cho nhánh DB
# # ============================================================

# def build_principal_from_session() -> Dict[str, Any]:
#     """
#     Helper dùng trong chat.py / db_router:
#         principal = build_principal_from_session()

#     Trả về:
#       {
#         "id":        staff_id hoặc user_id,
#         "username":  username,
#         "role":      'ADMIN'/'MANAGER'/'SALE'/'OTHER',
#         "raw_roles": [danh sách role chuẩn hoá],
#       }
#     """
#     username = session.get("user") or ""
#     staff_id = session.get("staff_id") or session.get("user_id")

#     raw_roles = []

#     r_single = session.get("role")
#     if r_single:
#         raw_roles.append(r_single)

#     r_multi = session.get("roles", [])
#     if isinstance(r_multi, (list, tuple, set)):
#         raw_roles.extend(list(r_multi))
#     else:
#         raw_roles.extend(_split_roles(r_multi))

#     norm = {_normalize_role_token(r) for r in raw_roles}

#     # Map sang role logic cho DB
#     if "admin" in norm:
#         app_role = "ADMIN"
#     elif "manager_sales" in norm or "manager_marketing" in norm:
#         app_role = "LEAD_SALE"
#     elif "sales" in norm:
#         app_role = "STAFF_SALE"
#     elif "accountant" in norm:
#         app_role = "ACCOUNTANT"
#     elif "hr" in norm:
#         app_role = "HR"
#     elif "warehouse" in norm:
#         app_role = "WAREHOUSE"
#     else:
#         app_role = "OTHER"

#     return {
#         "id": staff_id,
#         "username": username,
#         "role": app_role,
#         "raw_roles": sorted(list(norm)),
#     }


from __future__ import annotations

import re
from functools import wraps
from typing import List, Set, Dict, Any, Optional

import bcrypt  # 🔴 SỬA: Thêm bcrypt nếu chưa có
from flask import session, request, redirect, url_for, jsonify

try:
    from app.Model_LLM.Chat_Database.db_cli import fetch_table_all
except Exception:
    from app.Model_LLM.Chat_Database.db_cli import fetch_table_all

# ============================================================
# 1. Role hợp lệ + helper chuẩn hoá – 🔴 SỬA: CORE_ROLES không dùng filter
# ============================================================

CORE_ROLES = {  # 🔴 SỬA: Đổi tên, chỉ dùng map logic, không filter custom
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
    if t in {"hr", "human_resources", "human resources"}:
        return "hr"
    if t in {"staff_warehouse_domestic", "staff_warehouse_foreign"}:
        return "warehouse"
    return t.lower()  # 🔴 SỬA: Giữ nguyên custom nếu không map


def normalize_roles(raw_roles) -> List[str]:
    """
    Chuẩn hoá role lấy từ DB hoặc user:
      - đầu vào: string ("sales, manager_sales, custom_dev") HOẶC list
      - đầu ra: list role không trùng, đã normalize, GIỮ CUSTOM (không filter)
    """
    tokens = [_normalize_role_token(x) for x in _split_roles(raw_roles)]
    # 🔴 SỬA: Bỏ filter: tokens = [r for r in tokens if r in ALLOWED_ROLES or r == "admin"]
    seen: Set[str] = set()
    out: List[str] = []
    for r in tokens:
        if r not in seen:
            seen.add(r)
            out.append(r)
    print(f"[normalize_roles] Raw: '{raw_roles}' → Output: {out}")  # 🔴 SỬA: Debug log
    return out


# ============================================================
# 2. get_user: lấy user từ bảng account thật (API Supabase) – 🔴 SỬA: Hash + nhiều cột
# ============================================================

def get_user(username: str) -> Optional[Dict[str, Any]]:
    """
    Lấy user thật từ bảng `account` qua API.

    Trả về dict chuẩn hoá:
      {
        "id": account_id or username,
        "username": str,
        "password_hash": str (BCrypt hash),  # 🔴 SỬA: Hash thay plain
        "role": str (role chính),
        "roles": [list role đã normalize, GIỮ CUSTOM],
        "staff_id": staff_id or account_id or username,
        "account_id": account_id,
        "status": "HOAT_DONG" / "BI_KHOA" / ... (nếu có)
      }
    hoặc None nếu không tìm thấy.
    """
    username = (username or "").strip()
    if not username:
        return None

    # 🔴 SỬA: Thử nhiều cột phổ biến trong DB Việt Nam (Supabase)
    possible_columns = ["ten_dang_nhap", "username", "email", "sdt", "phone", "tai_khoan", "user_name"]
    rows = None
    used_column = None
    for col in possible_columns:
        try:
            rows = fetch_table_all(
                "account",
                params={f"eq__{col}": username},  # 🔴 SỬA: Động theo cột
                page_size=5,
                max_pages=1,
            )
            if rows:
                used_column = col
                print(f"[get_user] Tìm thấy '{username}' bằng cột: {col}")
                break
        except Exception as e:
            print(f"[get_user] Lỗi cột {col}: {e}")
            continue

    if not rows:
        print(f"[get_user] Không tìm thấy user: {username}")
        return None

    row = rows[0]

    # 🔴 SỬA: Password HASH (BCrypt từ Spring), không plain
    hashed_password = (
        row.get("password")
        or row.get("password_hash")
        or row.get("hashed_password")
        or ""
    )

    # Role / roles – dùng normalize mới (giữ custom)
    raw_roles = row.get("roles")
    if not raw_roles:
        raw_roles = row.get("role") or ""

    roles = normalize_roles(raw_roles)  # 🔴 SỬA: Giữ custom, có log
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

    user_dict = {
        "id": account_id or username,
        "username": row.get("username") or username,
        "password_hash": hashed_password,  # 🔴 SỬA: Key mới cho hash
        "role": main_role,
        "roles": roles,  # Giữ custom
        "staff_id": staff_id,
        "account_id": account_id,
        "status": status,
        "status_raw": raw_status,
        "_raw": row,
        "_found_by": used_column,
    }
    print(f"[get_user] Roles: {roles} | Status: {status} | Hash starts with $2: {hashed_password.startswith('$2')}")  # 🔴 SỬA: Debug
    return user_dict


# ============================================================
# 3. login_required decorator – 🔴 SỬA: Không filter custom
# ============================================================

def _normalize_required(roles) -> Set[str]:
    return set(_split_roles(roles)) if roles else set()


def _get_session_roles() -> Set[str]:
    """
    Lấy full tập role hiện tại từ session: GIỮ CUSTOM
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

    # 🔴 SỬA: Bỏ filter: have = {r for r in have if r in ALLOWED_ROLES or r == "admin"}
    print(f"[_get_session_roles] Have (full): {have}")  # 🔴 SỬA: Debug
    return have


def login_required(view=None, *, api: bool = False, roles=None):
    """
    Dùng:
      @login_required
      @login_required(api=True)
      @login_required(roles="sales,manager_sales,custom_dev")  # Hỗ trợ custom

    - Nếu chưa có session["user"]: 401/redirect
    - Nếu có roles yêu cầu: cho qua nếu intersect với need (giữ custom)
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
                    print(f"[login_required] Forbidden: need={need}, have={have}")  # 🔴 SỬA: Debug
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
# 4. build_principal_from_session – 🔴 SỬA: Map custom sang "CUSTOM"
# ============================================================

def build_principal_from_session() -> Dict[str, Any]:
    """
    Helper dùng trong chat.py / db_router:
        principal = build_principal_from_session()

    Trả về:
      {
        "id":        staff_id hoặc user_id,
        "username":  username,
        "role":      'ADMIN'/'LEAD_SALE'/'STAFF_SALE'/'CUSTOM'/'OTHER',
        "raw_roles": [danh sách role chuẩn hoá, GIỮ CUSTOM],
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

    # Map sang role logic cho DB – ưu tiên core, fallback custom
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
    elif "customer" in norm:
        app_role = "CUSTOMER"
    else:
        # 🔴 SỬA: Nếu custom (không core) → "CUSTOM"
        custom = norm - CORE_ROLES
        app_role = "CUSTOM" if custom else "OTHER"

    principal = {
        "id": staff_id,
        "username": username,
        "role": app_role,
        "raw_roles": sorted(list(norm)),  # Giữ custom
    }
    print(f"[build_principal] App role: {app_role} | Raw roles: {principal['raw_roles']}")  # 🔴 SỬA: Debug
    return principal