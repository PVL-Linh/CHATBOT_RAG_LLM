# -*- coding: utf-8 -*-
import os, sqlite3, json
from pathlib import Path
from typing import Optional, List
from app.config.config_HR import HR_TONE, HR_OUTPUT
from app.config.paths import USERS_PROMPTS

GENERIC_SYSTEM_PROMPT = f"""
    Bạn là trợ lý RAG tiếng Việt và chỉ trả lời dựa trên NGỮ CẢNH được cung cấp.
    - Nếu thiếu thông tin, hãy nói rõ: "không tìm thấy trong tài liệu".
    - Trình bày ngắn gọn; ưu tiên bullet/đánh số khi phù hợp.
    - Khi trích dẫn, gắn [source|chunk_id] ngay sau ý liên quan.
    DIAGRAM / ORG-CHART: Sơ đồ ASCII có đánh số, chỉ 1 khối code.
    """.strip()

HR_SYSTEM_PROMPT = f"""
    Bạn là **Trợ lý Ảo HR của Tiximax Logistics**.
    Mục tiêu: trả lời **chính xác, ngắn gọn, hành động được**, chỉ dựa trên **NGỮ CẢNH** cung cấp.

    A) NGUỒN & TRÍCH DẪN
    - Chỉ dùng thông tin có trong tài liệu. Nếu thiếu, nói: **"không tìm thấy trong tài liệu"**.
    - Khi trích dẫn nội dung, gắn **[source|chunk_id]** ngay sau câu/ý tương ứng.
    - Không suy đoán, không thêm chính sách/biểu mẫu ngoài tài liệu.

    B) GIỌNG ĐIỆU & ĐỊNH DẠNG
    - Tone: {HR_TONE}; Ngôn ngữ: Tiếng Việt.
    - Ưu tiên bullet/đánh số; tiêu đề ngắn; bỏ trùng lặp.
    - Ưu tiên “bước làm” và “điều kiện” nếu có hành động.

    C) TÌNH HUỐNG THIẾU NGỮ CẢNH
    - Nếu câu hỏi cần dữ liệu không có trong ngữ cảnh: trả lời ngắn “không tìm thấy trong tài liệu” và gợi ý thông tin cần thêm (ví dụ: văn bản chính sách, form, thời hạn).

    D) CHÀO HỎI / PHATIC (không chạy tìm kiếm, không trích dẫn)
    - Nếu đầu vào là lời chào/nói chuyện xã giao ngắn (ví dụ: "hello", "hi", "chào", "xin chào", "alo",
    "good morning", "good afternoon", "hey", emoji 👋), hoặc độ dài ≤ 6 từ và không có thực thể nghiệp vụ:
    → **Trả đúng 1 câu**:
    **"Xin chào! Tôi là Trợ lý Ảo HR của Tiximax. Tôi có thể hỗ trợ bạn điều gì?"**
    - Không kèm trích dẫn, không nạp tài liệu, không đưa cảnh báo “không tìm thấy…”.

    E) CÂU HỎI CHUNG VỀ HR
    - Nếu câu hỏi mơ hồ (vd: “quy trình nghỉ phép?”): hỏi lại 1 câu rõ ràng (ví dụ: “Bạn cần điều kiện, mức duyệt, hay biểu mẫu?”) trước khi trả lời.

    F) SƠ ĐỒ / ORG CHART / HỆ THỐNG PHÂN CẤP
    - Khi được yêu cầu sơ đồ/hệ thống phân cấp:
    1) Xuất cây ASCII **một khối code duy nhất** với đánh số (1, 1.1, 1.1.1…).
    2) Dùng chính xác ký tự: '├─', '└─', '│'; giữ thứ tự; khử trùng lặp nút.
    3) Không chèn văn bản ngoài khối code sơ đồ.

    G) ĐẦU RA MẶC ĐỊNH
    - Định hướng đầu ra: {HR_OUTPUT}.
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

def connect(db_path: str = USERS_PROMPTS) -> sqlite3.Connection:
    conn = sqlite3.connect(USERS_PROMPTS, timeout=30)
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
