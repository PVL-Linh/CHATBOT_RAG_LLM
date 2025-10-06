# -*- coding: utf-8 -*-
import os, sqlite3, json
from pathlib import Path
from typing import Optional, List
from .config_hr import HR_TONE, HR_OUTPUT

GENERIC_SYSTEM_PROMPT = f"""
Bạn là trợ lý RAG tiếng Việt và chỉ trả lời dựa trên NGỮ CẢNH được cung cấp.
- Nếu thiếu thông tin, hãy nói rõ: "không tìm thấy trong tài liệu".
- Trình bày ngắn gọn; ưu tiên bullet/đánh số khi phù hợp.
- Khi trích dẫn, gắn [source|chunk_id] ngay sau ý liên quan.
DIAGRAM / ORG-CHART: Sơ đồ ASCII có đánh số, chỉ 1 khối code.
""".strip()

HR_SYSTEM_PROMPT = f"""
Bạn là **RAG Assistant của phòng Nhân sự (HR) – Tiximax Logistics**.
Mục tiêu: trả lời **chính xác, ngắn gọn, hành động được**, chỉ dựa trên **NGỮ CẢNH** cung cấp.

A) NGUỒN & TRÍCH DẪN
- Chỉ dùng thông tin có trong tài liệu. Nếu thiếu: **"không tìm thấy trong tài liệu"**.
- Gắn **[source|chunk_id]** ngay sau câu/ý.

B) GIỌNG ĐIỆU & ĐỊNH DẠNG
- Tone: {HR_TONE}; Ngôn ngữ: tiếng Việt; ưu tiên bullet/đánh số; loại bỏ trùng lặp.

G) SƠ ĐỒ / ORG CHART / HIERARCHY
- Với yêu cầu sơ đồ/hệ thống phân cấp:
  1) Xuất cây ASCII có đánh số (1, 1.1, 1.1.1…).
  2) Dùng chính xác '├─', '└─', '│'; giữ thứ tự, khử lặp nút.
  3) Không tạo hai khối sơ đồ; chỉ **một** khối code.
""".strip()

SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  key        TEXT NOT NULL,
  profile    TEXT NOT NULL,
  version    INTEGER NOT NULL DEFAULT 1,
  content    TEXT NOT NULL,
  meta       TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(key, version)
);
CREATE INDEX IF NOT EXISTS idx_prompts_key ON prompts(key);
"""

def _find_project_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / "src" / "app").exists():
            return p
    return None

def _resolve_db_path() -> str:
    env_path = os.getenv("PROMPT_DB")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)
    here = Path(__file__).resolve()
    root = _find_project_root(here)
    data_dir = (root / "src" / "app" / "Data_app") if root else (here.parent / "Data_app")
    data_dir.mkdir(parents=True, exist_ok=True)
    return str((data_dir / "prompts.db").resolve())

DB_PATH = _resolve_db_path()

def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def upsert_prompt(conn: sqlite3.Connection, key: str, profile: str, content: str, meta: dict=None, version: int=None) -> int:
    if version is None:
        cur = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM prompts WHERE key=?", (key,))
        (version,) = cur.fetchone()
    conn.execute(
        "INSERT INTO prompts(key, profile, version, content, meta, created_at, updated_at) VALUES(?,?,?,?,json(?),datetime('now'),datetime('now'))",
        (key, profile, version, content, json.dumps(meta or {}))
    )
    conn.commit()
    return version

def get_prompt(conn: sqlite3.Connection, key: str, version: int=None):
    if version is None:
        row = conn.execute("SELECT content, COALESCE(meta,'{}') FROM prompts WHERE key=? ORDER BY version DESC LIMIT 1", (key,)).fetchone()
    else:
        row = conn.execute("SELECT content, COALESCE(meta,'{}') FROM prompts WHERE key=? AND version=?", (key,)).fetchone()
    if not row: return None
    content, meta = row
    return content, json.loads(meta)

def seed_defaults_if_empty() -> None:
    conn = connect()
    try:
        row = conn.execute("SELECT 1 FROM prompts WHERE key='system:HR' LIMIT 1").fetchone()
        if not row:
            upsert_prompt(conn, key="system:HR", profile="HR", content=HR_SYSTEM_PROMPT.strip(), meta={"tone": HR_TONE, "output": HR_OUTPUT})
        row = conn.execute("SELECT 1 FROM prompts WHERE key='system:GENERIC' LIMIT 1").fetchone()
        if not row:
            upsert_prompt(conn, key="system:GENERIC", profile="GENERIC", content=GENERIC_SYSTEM_PROMPT.strip(), meta={"lang":"vi"})
    finally:
        conn.close()

def get_system_prompt(profile: str = "HR") -> str:
    key = "system:HR" if (profile or "").upper() == "HR" else "system:GENERIC"
    conn = connect()
    try:
        row = get_prompt(conn, key)
        if row:
            content, _meta = row
            return content
        return HR_SYSTEM_PROMPT if key == "system:HR" else GENERIC_SYSTEM_PROMPT
    finally:
        conn.close()
