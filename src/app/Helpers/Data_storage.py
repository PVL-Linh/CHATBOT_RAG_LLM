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

def _ensure_db() -> None:
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
    return sqlite3.connect(DB_PATH_MARKETING, timeout=30, check_same_thread=False)


def migrate_json_to_sqlite(default_username: str = "") -> int:
    """
    Một lần duy nhất: nhập saved.json cũ vào sqlite.
    Trả về số bản ghi đã import. Bỏ qua nếu file không tồn tại.
    """
    _ensure_db()
    if not os.path.exists(JSON_SAVED_PATH):
        return 0

    with open(JSON_SAVED_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f) or {}
        except Exception:
            data = {}
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

    try:
        os.replace(JSON_SAVED_PATH, JSON_SAVED_PATH + ".migrated.bak")
    except Exception:
        pass

    return total

def save_item(
    item_type: str,
    text: str,
    input_data: Optional[Dict] = None,
    meta: Optional[Dict] = None,
    username: str = ""
    ) -> Dict[str, Any]:
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

def load_all_grouped(username: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
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
