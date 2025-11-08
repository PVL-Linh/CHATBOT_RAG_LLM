# sql3.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import sqlite3, json, time
from contextlib import contextmanager
from typing import Dict, Any, Optional, List, Tuple
import os

def _ensure_dir(p: str):
    d = os.path.dirname(p or "")
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

@contextmanager
def _conn(db_path: str):
    _ensure_dir(db_path)
    con = sqlite3.connect(db_path, timeout=30)
    try:
        yield con
    finally:
        con.commit()
        con.close()

# ------------------------------------------------------------------------------
# Schema & Migration
# ------------------------------------------------------------------------------
def init_db(db_path: str):
    """Create tables if not exists, then run migrations (add columns, etc.)."""
    with _conn(db_path) as con:
        cur = con.cursor()
        # Lưu lịch sử hội thoại
        cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,   -- 'user' | 'assistant'
            content    TEXT NOT NULL,
            ts         REAL NOT NULL    -- epoch seconds
            -- meta TEXT  (thêm bằng migration)
        )
        """)
        # KV lưu context hội thoại
        cur.execute("""
        CREATE TABLE IF NOT EXISTS session_kv (
            session_id TEXT NOT NULL,
            k          TEXT NOT NULL,
            v          TEXT NOT NULL,
            ts         REAL NOT NULL,
            PRIMARY KEY (session_id, k)
        )
        """)
    migrate_schema(db_path)

def migrate_schema(db_path: str):
    """Add missing columns/indices safely."""
    with _conn(db_path) as con:
        cur = con.cursor()
        # --- history.meta TEXT DEFAULT '{}' ---
        cur.execute("PRAGMA table_info(history)")
        cols = [r[1] for r in cur.fetchall()]  # r[1] = name
        if "meta" not in cols:
            cur.execute("ALTER TABLE history ADD COLUMN meta TEXT DEFAULT '{}'")
        # optional index for speed
        cur.execute("CREATE INDEX IF NOT EXISTS idx_history_session_ts ON history(session_id, ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_session_kv_session ON session_kv(session_id)")

# ------------------------------------------------------------------------------
# Basic message history
# ------------------------------------------------------------------------------
def save_message(session_id: str, role: str, content: str, db_path: str, meta: Optional[Dict[str, Any]] = None):
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    with _conn(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO history(session_id, role, content, ts, meta) VALUES(?,?,?,?,?)",
            (session_id, role, content, time.time(), meta_json),
        )

def get_recent_messages(session_id: str, limit: int, db_path: str) -> List[Dict[str, Any]]:
    with _conn(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT role, content, ts, meta FROM history WHERE session_id=? ORDER BY ts DESC LIMIT ?",
            (session_id, int(limit)),
        )
        rows = []
        for r in cur.fetchall():
            role, content, ts, meta_raw = r
            try:
                meta_obj = json.loads(meta_raw or "{}")
            except Exception:
                meta_obj = {}
            rows.append({"role": role, "content": content, "ts": ts, "meta": meta_obj})
        return rows

def touch_session(session_id: str, db_path: str):
    # No-op placeholder (để tương thích)
    return True

# ------------------------------------------------------------------------------
# Simple KV helpers for session context
# Keys được services.py sử dụng:
#   last_order_code, last_period (dict with dt_from/dt_to), last_topic, last_top
# ------------------------------------------------------------------------------
def _kv_set(session_id: str, key: str, val: Any, db_path: str):
    with _conn(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO session_kv(session_id, k, v, ts) VALUES(?,?,?,?) "
            "ON CONFLICT(session_id, k) DO UPDATE SET v=excluded.v, ts=excluded.ts",
            (session_id, key, json.dumps(val, ensure_ascii=False), time.time()),
        )

def _kv_get(session_id: str, key: str, db_path: str) -> Optional[Any]:
    with _conn(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT v FROM session_kv WHERE session_id=? AND k=?",
            (session_id, key),
        )
        r = cur.fetchone()
        if not r:
            return None
        try:
            return json.loads(r[0])
        except Exception:
            return None

# ---- last_order_code ---------------------------------------------------------
def set_last_order_code(session_id: str, code: str, db_path: str):
    _kv_set(session_id, "last_order_code", code, db_path)

def get_last_order_code(session_id: str, db_path: str) -> Optional[str]:
    v = _kv_get(session_id, "last_order_code", db_path)
    return v if isinstance(v, str) else None

# ---- last_period -------------------------------------------------------------
def set_last_period(session_id: str, dt_from: str, dt_to: str, db_path: str, last_intent: Optional[str] = None):
    payload = {"dt_from": dt_from, "dt_to": dt_to, "last_intent": last_intent}
    _kv_set(session_id, "last_period", payload, db_path)

def get_last_period(session_id: str, db_path: str) -> Optional[Dict[str, Any]]:
    v = _kv_get(session_id, "last_period", db_path)
    return v if isinstance(v, dict) else None

# ---- last_topic --------------------------------------------------------------
def set_last_topic(session_id: str, topic: str, db_path: str):
    _kv_set(session_id, "last_topic", topic, db_path)

def get_last_topic(session_id: str, db_path: str) -> Optional[str]:
    v = _kv_get(session_id, "last_topic", db_path)
    return v if isinstance(v, str) else None

# ---- last_top (store bảng xếp hạng gần nhất) --------------------------------
def set_last_top(session_id: str, data: Dict[str, Any], db_path: str):
    # data dụ kiến có keys: items (list), meta (dict: label, period,...)
    _kv_set(session_id, "last_top", data, db_path)

def get_last_top(session_id: str, db_path: str) -> Optional[Dict[str, Any]]:
    v = _kv_get(session_id, "last_top", db_path)
    return v if isinstance(v, dict) else None
