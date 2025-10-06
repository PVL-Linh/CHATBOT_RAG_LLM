# -*- coding: utf-8 -*-
# app/rag_hr/data_config.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

# Tên biến môi trường để chỉ định file DB
ENV_DB_PATH = "PATH_CHAT_HR"

# Giá trị mặc định khi không set ENV (relative đến project root)
DEFAULT_RELATIVE_DB = "src/app/Data_app/chat_hr.db"

# Schema chuẩn cho lịch sử chat HR
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hr_sessions (
    id TEXT PRIMARY KEY,
    user TEXT NOT NULL,
    title TEXT DEFAULT 'Cuộc trò chuyện HR',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hr_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES hr_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_hr_messages_session
ON hr_messages(session_id, timestamp);
"""

def _find_project_root(start: Path) -> Optional[Path]:
    """
    Tìm project root qua dấu hiệu có thư mục src/app.
    """
    for p in [start] + list(start.parents):
        if (p / "src" / "app").exists():
            return p
    return None

def resolve_db_path() -> Path:
    """
    Ưu tiên ENV (PATH_CHAT_HR). Nếu là relative, chuẩn hoá theo project root (nếu có).
    Nếu không có ENV, dùng DEFAULT_RELATIVE_DB.
    """
    here = Path(__file__).resolve()
    env_p = os.getenv(ENV_DB_PATH, "").strip()
    if env_p:
        p = Path(env_p)
        if not p.is_absolute():
            root = _find_project_root(here)
            p = (root / p).resolve() if root else (here.parent / p).resolve()
        return p

    root = _find_project_root(here)
    return ((root / DEFAULT_RELATIVE_DB).resolve()
            if root else (here.parent / "Data_app" / "chat_hr.db").resolve())
