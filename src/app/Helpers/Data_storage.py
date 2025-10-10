# import os
# import json
# from typing import Dict, List, Any
# import time
# # Constants
# DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
# SAVED_PATH = os.path.join(DATA_DIR, "saved.json")

# def ensure_store() -> None:
#     """Ensure data directory and saved.json file exist"""
#     os.makedirs(DATA_DIR, exist_ok=True)
#     if not os.path.exists(SAVED_PATH):
#         with open(SAVED_PATH, "w", encoding="utf-8") as f:
#             json.dump({"fbads": [], "rephrase": [], "tiktok": [], "fab": []}, f, ensure_ascii=False, indent=2)

# def load_saves() -> Dict[str, List[Any]]:
#     """Load saved data from JSON file"""
#     ensure_store()
#     with open(SAVED_PATH, "r", encoding="utf-8") as f:
#         return json.load(f)

# def save_saves(data: Dict[str, List[Any]]) -> None:
#     """Save data to JSON file"""
#     with open(SAVED_PATH, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)

# def save_item(item_type: str, text: str, input_data: Dict = None, meta: Dict = None) -> Dict[str, Any]:
#     """Save a single item to storage"""

    
#     item = {
#         "ts": int(time.time()),
#         "text": text,
#         "input": input_data or {},
#         "meta": meta or {}
#     }
    
#     data = load_saves()
#     data.setdefault(item_type, [])
#     data[item_type].insert(0, item)
#     save_saves(data)
    
#     return item

# def delete_item(item_type: str, timestamp: int) -> bool:
#     """Delete an item by timestamp"""
#     data = load_saves()
#     data.setdefault(item_type, [])
    
#     original_count = len(data[item_type])
#     data[item_type] = [x for x in data[item_type] if x.get("ts") != timestamp]
#     save_saves(data)
    
#     return len(data[item_type]) < original_count

# def get_items(item_type: str) -> List[Dict[str, Any]]:
#     """Get all items of a specific type"""
#     return load_saves().get(item_type, [])

# src/app/Storage/saved_store_sqlite.py
# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import threading
import time
from typing import Dict, List, Any, Optional
from app.config.paths import DATA_APP_DIR, DB_PATH_MARKETING


JSON_DATA_DIR = os.path.join(str(DATA_APP_DIR))
JSON_SAVED_PATH = os.path.join(JSON_DATA_DIR, "saved_marketing.json") 

_DB_LOCK = threading.Lock()
_DB_READY = False


# =========================
# DB setup
# =========================
def _ensure_db() -> None:
    """Khởi tạo DB (WAL, bảng, index) — gọi tự động trước mỗi thao tác."""
    global _DB_READY
    if _DB_READY:
        return
    with _DB_LOCK:
        if _DB_READY:
            return

        os.makedirs(os.path.dirname(DB_PATH_MARKETING) or ".", exist_ok=True)
        con = sqlite3.connect(DB_PATH_MARKETING, timeout=30)
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute("PRAGMA busy_timeout=5000;")

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_items(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    username TEXT DEFAULT '',
                    text TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    meta_json TEXT NOT NULL
                );
                """
            )
            # Index để query nhanh theo type/user/time
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_saved_items_type_user_ts "
                "ON saved_items(item_type, username, ts DESC);"
            )
            con.commit()
            _DB_READY = True
        finally:
            con.close()


def _conn():
    _ensure_db()
    # Cho phép cross-thread
    return sqlite3.connect(DB_PATH_MARKETING, timeout=30, check_same_thread=False)


# =========================
# (Tuỳ chọn) migrate từ JSON cũ
# =========================
def migrate_json_to_sqlite(default_username: str = "") -> int:
    """
    Một lần duy nhất: nhập saved.json cũ vào sqlite.
    Trả về số bản ghi đã import. Bỏ qua nếu file không tồn tại.
    """
    _ensure_db()
    if not os.path.exists(JSON_SAVED_PATH):
        return 0

    # Đọc JSON cũ
    with open(JSON_SAVED_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f) or {}
        except Exception:
            data = {}

    # Dữ liệu cũ có keys: "fbads": [], "rephrase": [], "tiktok": [], "fab": []
    total = 0
    con = _conn()
    try:
        for item_type, items in (data.items() if isinstance(data, dict) else []):
            if not isinstance(items, list):
                continue
            for it in items:
                ts = int(it.get("ts") or time.time())
                text = str(it.get("text") or "")
                input_json = json.dumps(it.get("input") or {}, ensure_ascii=False)
                meta_json = json.dumps(it.get("meta") or {}, ensure_ascii=False)
                con.execute(
                    "INSERT INTO saved_items(item_type, ts, username, text, input_json, meta_json) "
                    "VALUES (?,?,?,?,?,?)",
                    (item_type, ts, default_username, text, input_json, meta_json),
                )
                total += 1
        con.commit()
    finally:
        con.close()

    # Tuỳ chọn: đổi tên file cũ để tránh import lại
    try:
        os.replace(JSON_SAVED_PATH, JSON_SAVED_PATH + ".migrated.bak")
    except Exception:
        pass

    return total


# =========================
# API tương tự bản JSON (có thêm username)
# =========================
def save_item(
    item_type: str,
    text: str,
    input_data: Optional[Dict] = None,
    meta: Optional[Dict] = None,
    username: str = ""
) -> Dict[str, Any]:
    """
    Lưu 1 item. Trả về dict item vừa lưu.
    - item_type: "fbads" | "rephrase" | "tiktok" | "fab" | ... (tự do)
    - username: có thể để trống nếu không cần phân quyền
    """
    _ensure_db()
    ts = int(time.time())
    input_json = json.dumps(input_data or {}, ensure_ascii=False)
    meta_json = json.dumps(meta or {}, ensure_ascii=False)

    con = _conn()
    try:
        con.execute(
            "INSERT INTO saved_items(item_type, ts, username, text, input_json, meta_json) "
            "VALUES (?,?,?,?,?,?)",
            (item_type, ts, username, text, input_json, meta_json),
        )
        con.commit()
    finally:
        con.close()

    return {
        "ts": ts,
        "text": text,
        "input": input_data or {},
        "meta": meta or {},
        "username": username,
        "item_type": item_type,
    }


def delete_item(item_type: str, timestamp: int, username: Optional[str] = None) -> bool:
    """
    Xoá item theo ts. Nếu có username thì chỉ xoá bản ghi thuộc user đó.
    Trả về True nếu có ít nhất 1 bản ghi bị xoá.
    """
    _ensure_db()
    con = _conn()
    try:
        if username is None:
            cur = con.execute(
                "DELETE FROM saved_items WHERE item_type=? AND ts=?",
                (item_type, int(timestamp)),
            )
        else:
            cur = con.execute(
                "DELETE FROM saved_items WHERE item_type=? AND ts=? AND username=?",
                (item_type, int(timestamp), username),
            )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def get_items(
    item_type: str,
    username: Optional[str] = None,
    limit: int = 200,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Lấy danh sách item theo loại (và theo user nếu có).
    Mặc định sort mới → cũ (ts DESC).
    """
    _ensure_db()
    con = _conn()
    con.row_factory = sqlite3.Row
    try:
        if username is None:
            rows = con.execute(
                "SELECT item_type, ts, username, text, input_json, meta_json "
                "FROM saved_items WHERE item_type=? "
                "ORDER BY ts DESC LIMIT ? OFFSET ?",
                (item_type, int(limit), int(offset)),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT item_type, ts, username, text, input_json, meta_json "
                "FROM saved_items WHERE item_type=? AND username=? "
                "ORDER BY ts DESC LIMIT ? OFFSET ?",
                (item_type, username, int(limit), int(offset)),
            ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "item_type": r["item_type"],
                "ts": r["ts"],
                "username": r["username"],
                "text": r["text"],
                "input": json.loads(r["input_json"] or "{}"),
                "meta": json.loads(r["meta_json"] or "{}"),
            })
        return out
    finally:
        con.close()


# =========================
# (Tuỳ chọn) API load/save toàn bộ kiểu cũ
# =========================
def load_all_grouped(username: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Trả về dict {item_type: [items...]} để tương thích cao với bản JSON cũ.
    Nếu có username, chỉ lấy của user đó.
    """
    _ensure_db()
    con = _conn()
    con.row_factory = sqlite3.Row
    try:
        if username is None:
            rows = con.execute(
                "SELECT item_type, ts, username, text, input_json, meta_json FROM saved_items ORDER BY ts DESC"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT item_type, ts, username, text, input_json, meta_json FROM saved_items WHERE username=? ORDER BY ts DESC",
                (username,),
            ).fetchall()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            it = r["item_type"]
            grouped.setdefault(it, []).append({
                "item_type": it,
                "ts": r["ts"],
                "username": r["username"],
                "text": r["text"],
                "input": json.loads(r["input_json"] or "{}"),
                "meta": json.loads(r["meta_json"] or "{}"),
            })
        return grouped
    finally:
        con.close()
