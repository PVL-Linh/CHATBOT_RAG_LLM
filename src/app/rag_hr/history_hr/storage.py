# -*- coding: utf-8 -*-
# app/rag_hr/storage.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

from .data_config import resolve_db_path, SCHEMA_SQL

_DB_PATH: Path = resolve_db_path()

def db_path() -> str:
    """Trả về đường dẫn DB (string) hiện đang dùng."""
    return str(_DB_PATH)

def set_db_path(new_path: str, init: bool = False) -> None:
    """
    Override DB path lúc runtime (test/benchmark).
    """
    global _DB_PATH
    p = Path(new_path).resolve()
    _DB_PATH = p
    if init:
        init_db()

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def get_conn() -> sqlite3.Connection:
    """
    Lấy kết nối SQLite bật WAL + FK, dùng ổn định cho Flask multi-thread.
    """
    _ensure_parent(_DB_PATH)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return conn

@contextmanager
def conn_ctx():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()

def init_db() -> None:
    _ensure_parent(_DB_PATH)
    with conn_ctx() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

# Init idempotent khi import
init_db()
