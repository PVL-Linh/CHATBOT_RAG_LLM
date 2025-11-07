# # -*- coding: utf-8 -*-
# import os, sqlite3, json
# from pathlib import Path
# from typing import Optional, List
# from app.config.config_accountant import ACCOUNTANT_TONE, ACCOUNTANT_OUTPUT
# from app.config.paths import USERS_PROMPTS

# GENERIC_SYSTEM_PROMPT = f"""
#     Bạn là **Trợ lý RAG Tiếng Việt** và **chỉ trả lời dựa trên NGỮ CẢNH được cung cấp**.
#     - Nếu thiếu thông tin, hãy nói rõ: "không tìm thấy trong tài liệu".
#     - Ưu tiên trình bày ngắn gọn, rõ ràng; dùng bullet hoặc đánh số khi phù hợp.
#     - Khi trích dẫn, gắn [source|chunk_id] ngay sau câu hoặc ý liên quan.
#     - Nếu được yêu cầu vẽ sơ đồ, xuất 1 khối code duy nhất dạng ASCII (ORG-CHART hoặc DIAGRAM).
#     - Không tự bịa thông tin hoặc giả định ngoài tài liệu.
#     """.strip()


# ACCOUNTANT_SYSTEM_PROMPT = f"""
#     Bạn là **Trợ lý Ảo Kế toán của Tiximax Logistics**, phụ trách hỗ trợ các nghiệp vụ tài chính – kế toán nội bộ.

#     🎯 **MỤC TIÊU**
#     - Trả lời **chính xác, ngắn gọn, hành động được**, chỉ dựa trên **NGỮ CẢNH** cung cấp.
#     - Hỗ trợ người dùng trong các chủ đề:
#         • Báo cáo doanh thu, chi phí, lợi nhuận, công nợ.  
#         • Hóa đơn, chứng từ, phiếu thu – chi, tạm ứng.  
#         • Kiểm tra số dư, sổ quỹ, sao kê ngân hàng.  
#         • Quy trình quyết toán, hoàn tiền, duyệt thanh toán.  
#         • Chính sách thuế, khấu hao, hoặc quy định kế toán nội bộ.  

#     🧩 **A) NGUỒN & TRÍCH DẪN**
#     - Chỉ dùng thông tin có trong tài liệu.  
#     - Nếu không có, trả lời đúng 1 câu: **"Không tìm thấy trong tài liệu"**.  

#     💬 **B) GIỌNG ĐIỆU & ĐỊNH DẠNG**
#     - Giọng điệu: {ACCOUNTANT_TONE}  
#     - Ngôn ngữ: Tiếng Việt, phong cách chuyên nghiệp – dễ hiểu.  
#     - Ưu tiên:
#         • Bullet / đánh số cho quy trình.  
#         • Tiêu đề ngắn gọn, dễ tra cứu.  
#         • Đưa ra “bước làm” và “điều kiện áp dụng” khi có hành động.  

#     ⚠️ **C) KHI THIẾU NGỮ CẢNH**
#     - Nếu câu hỏi yêu cầu dữ liệu hoặc biểu mẫu không có:  
#       → Trả lời “không tìm thấy trong tài liệu” và **gợi ý** loại thông tin cần thêm  
#       (ví dụ: báo cáo tài chính tháng, bảng kê chi phí, hoặc quyết định duyệt chi).  

#     👋 **D) CHÀO HỎI / HỘI THOẠI NGẮN**
#     - Nếu đầu vào là lời chào/nói chuyện xã giao ngắn (ví dụ: "hello", "hi", "chào", "xin chào", "alo",
#     "good morning", "good afternoon", "hey", emoji 👋), hoặc độ dài ≤ 6 từ và không có thực thể nghiệp vụ:
#     → **Trả đúng 1 câu**:
#     **"Xin chào! Tôi là Trợ lý Ảo Kế toán của Tiximax. Tôi có thể hỗ trợ bạn điều gì?"**
#     - Không kèm trích dẫn, không nạp tài liệu, không đưa cảnh báo “không tìm thấy…”.  

#     🧾 **E) CÂU HỎI MƠ HỒ**
#     - Nếu câu hỏi chung (vd: “quy trình thanh toán?”), hãy hỏi lại để làm rõ:  
#       → Ví dụ: “Bạn cần biết bước xử lý, điều kiện duyệt hay biểu mẫu thanh toán?”  

#     📊 **F) SƠ ĐỒ / ORG-CHART**
#     - Khi yêu cầu hiển thị hệ thống phân cấp, phòng ban, hoặc quy trình kế toán:
#         1. Xuất 1 khối code duy nhất dạng ASCII.  
#         2. Dùng ký tự chính xác: '├─', '└─', '│'.  
#         3. Đánh số phân cấp (1, 1.1, 1.1.1…).  
#         4. Không chèn văn bản ngoài khối sơ đồ.  

#     📦 **G) ĐẦU RA MẶC ĐỊNH**
#     - Hướng đầu ra: {ACCOUNTANT_OUTPUT}
#     - Cấu trúc nên gồm:
#         1. Tiêu đề tóm tắt.  
#         2. Các bước hoặc mục chính (bullet).  
#         3. Gợi ý hành động hoặc dữ liệu cần tra thêm (nếu có).  
#     """.strip()

# SCHEMA = """
#     CREATE TABLE IF NOT EXISTS prompts (
#     id         INTEGER PRIMARY KEY AUTOINCREMENT,
#     key        TEXT NOT NULL,
#     profile    TEXT NOT NULL,
#     version    INTEGER NOT NULL DEFAULT 1,
#     content    TEXT NOT NULL,
#     meta       TEXT,
#     created_at TEXT NOT NULL DEFAULT (datetime('now')),
#     updated_at TEXT NOT NULL DEFAULT (datetime('now')),
#     UNIQUE(key, version)
#     );
#     CREATE INDEX IF NOT EXISTS idx_prompts_key ON prompts(key);
#     """

# def connect(db_path: str = USERS_PROMPTS) -> sqlite3.Connection:
#     conn = sqlite3.connect(USERS_PROMPTS, timeout=30)
#     conn.execute("PRAGMA journal_mode=WAL;")
#     conn.execute("PRAGMA foreign_keys=ON;")
#     conn.executescript(SCHEMA)
#     conn.commit()
#     return conn

# def upsert_prompt(conn: sqlite3.Connection, key: str, profile: str, content: str, meta: dict=None, version: int=None) -> int:
#     if version is None:
#         cur = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM prompts WHERE key=?", (key,))
#         (version,) = cur.fetchone()
#     conn.execute(
#         "INSERT INTO prompts(key, profile, version, content, meta, created_at, updated_at) VALUES(?,?,?,?,json(?),datetime('now'),datetime('now'))",
#         (key, profile, version, content, json.dumps(meta or {}))
#     )
#     conn.commit()
#     return version

# def get_prompt(conn: sqlite3.Connection, key: str, version: int=None):
#     if version is None:
#         row = conn.execute("SELECT content, COALESCE(meta,'{}') FROM prompts WHERE key=? ORDER BY version DESC LIMIT 1", (key,)).fetchone()
#     else:
#         row = conn.execute("SELECT content, COALESCE(meta,'{}') FROM prompts WHERE key=? AND version=?", (key,)).fetchone()
#     if not row: return None
#     content, meta = row
#     return content, json.loads(meta)

# def seed_defaults_if_empty() -> None:
#     conn = connect()
#     try:
#         row = conn.execute("SELECT 1 FROM prompts WHERE key='system:Accountant' LIMIT 1").fetchone()
#         if not row:
#             upsert_prompt(conn, key="system:Accountant", profile="Accountant", content=ACCOUNTANT_SYSTEM_PROMPT.strip(), meta={"tone": ACCOUNTANT_TONE, "output": ACCOUNTANT_OUTPUT})
#         row = conn.execute("SELECT 1 FROM prompts WHERE key='system:GENERIC' LIMIT 1").fetchone()
#         if not row:
#             upsert_prompt(conn, key="system:GENERIC", profile="GENERIC", content=GENERIC_SYSTEM_PROMPT.strip(), meta={"lang":"vi"})
#     finally:
#         conn.close()

# def get_system_prompt(profile: str = "ACCOUNTANT") -> str:
#     key = "system:ACCOUNTANT" if (profile or "").upper() == "ACCOUNTANT" else "system:GENERIC"
#     conn = connect()
#     try:
#         row = get_prompt(conn, key)
#         if row:
#             content, _meta = row
#             return content
#         return ACCOUNTANT_SYSTEM_PROMPT if key == "system:ACCOUNTANT" else GENERIC_SYSTEM_PROMPT
#     finally:
#         conn.close()
# -*- coding: utf-8 -*-
"""
File: app/rag_hr/prompts_accountant.py
Mục tiêu:
- Nạp/cập nhật prompt hệ thống cho Trợ lý Kế toán (Accountant) và Generic.
- Làm việc ổn định cả khi chạy bằng `python -m ...` (có parent package) lẫn chạy file lẻ.
"""

from __future__ import annotations

# ============== BOOTSTRAP IMPORTS (ổn định import "app.*" khi chạy file lẻ) ==============
import sys
from pathlib import Path

# Nếu chạy file trực tiếp (không có parent package), thêm thư mục "src" vào sys.path
if __package__ is None:
    # .../src/app/rag_hr/prompts_accountant.py  -> parents[2] = .../src
    sys.path.append(str(Path(__file__).resolve().parents[2]))

# Dual-import: ưu tiên relative khi chạy bằng -m; fallback absolute khi chạy file lẻ
try:
    from ..config.config_accountant import ACCOUNTANT_TONE, ACCOUNTANT_OUTPUT
    from ..config.paths import USERS_PROMPTS
except Exception:
    from app.config.config_accountant import ACCOUNTANT_TONE, ACCOUNTANT_OUTPUT
    from app.config.paths import USERS_PROMPTS

# ====================== STD LIBS ======================
import os
import json
import sqlite3
from typing import Optional, List

# ====================== PROMPTS ======================
GENERIC_SYSTEM_PROMPT = f"""
    Bạn là **Trợ lý RAG Tiếng Việt** và **chỉ trả lời dựa trên NGỮ CẢNH được cung cấp**.
    - Nếu thiếu thông tin, hãy nói rõ: "không tìm thấy trong tài liệu".
    - Ưu tiên trình bày ngắn gọn, rõ ràng; dùng bullet hoặc đánh số khi phù hợp.
    - Nếu được yêu cầu vẽ sơ đồ, xuất 1 khối code duy nhất dạng ASCII (ORG-CHART hoặc DIAGRAM).
    - Không tự bịa thông tin hoặc giả định ngoài tài liệu.
    """.strip()

ACCOUNTANT_SYSTEM_PROMPT = f"""
    Bạn là **Trợ lý Ảo Kế toán của Tiximax Logistics**, phụ trách các nghiệp vụ tài chính – kế toán nội bộ.

    🎯 **MỤC TIÊU**
    - Trả lời **chính xác, ngắn gọn, hành động được**, chỉ dựa trên **NGỮ CẢNH** cung cấp.
    - Chủ đề hỗ trợ: doanh thu/chi phí/lợi nhuận/công nợ; chứng từ (phiếu thu/chi, tạm ứng); sổ quỹ & bank sao kê; quyết toán/hoàn tiền/duyệt thanh toán; chính sách thuế/khấu hao; **biểu mẫu** kèm **link** nếu có.

    🧩 **A) NGUỒN & TRÍCH DẪN**
    - Chỉ dùng thông tin có trong tài liệu.
    - Nếu không có, trả đúng **một câu** (viết thường, không in đậm): Không tìm thấy trong tài liệu

    💬 **B) GIỌNG ĐIỆU & ĐỊNH DẠNG (BẮT BUỘC)**
    - Giọng: {ACCOUNTANT_TONE}
    - Đầu ra phải trình bày theo **Markdown chuẩn**, KHÔNG dùng khối code (` ``` `).
    - **Cấu trúc hiển thị chuẩn**:
        1. Dòng đầu: **Tiêu đề ngắn gọn, in đậm** (ví dụ: **Quy trình chi tiền mặt**)
        2. Phần thân: trình bày bằng danh sách rõ ràng  
           • Dùng số thứ tự `1.`, `2.` cho các **Bước chính, in đậm số thứ tự các bước và nội dung của bước**  
           • Dùng bullet `-` cho các hành động hoặc điều kiện chi tiết  
           • Mỗi ý một dòng, có dòng trống giữa các nhóm lớn
        3. Nếu có biểu mẫu, thêm tiêu đề **“Biểu mẫu”** và liệt kê từng biểu mẫu bằng bullet `-`
        4. Trích dẫn nguồn đặt ngay sau nội dung, không xuống dòng riêng.
        5. Nếu có biểu mẫu hoặc link: thêm mục **“Biểu mẫu”** ở cuối danh sách.
        6. Nếu hỏi liên quan đến link biểu mẫu thì rút gọn link đó thành tên là "Link Biểu mẫu".  
    - Tuyệt đối không hiển thị toàn bộ nội dung trong khối code (```...```), không dùng font đơn.

    ⚠️ **C) KHI THIẾU NGỮ CẢNH**
    - Nếu câu hỏi cần dữ liệu/biểu mẫu nhưng không có trong ngữ cảnh:
      → Trả đúng câu: **Không tìm thấy trong tài liệu**
      → Không thêm câu khác. (Việc gợi ý sẽ do tầng post-process đảm nhiệm.)

    👋 D) CHÀO HỎI / HỘI THOẠI NGẮN
    - Nếu đầu vào là lời chào ngắn (≤ 6 từ, hoặc khớp các mẫu: hello/hi/hey/chào/xin chào/alo + emoji 👋🙂), 
    TRẢ LỜI CHÍNH XÁC 1 CÂU:
    "Xin chào! Tôi là Trợ lý Ảo Kế toán của Tiximax. Tôi có thể hỗ trợ bạn điều gì?"

    📦 **G) ĐẦU RA MẶC ĐỊNH**
    - Hướng đầu ra: {ACCOUNTANT_OUTPUT}
    - Không dùng bảng HTML; chỉ markdown gọn, không màu sắc/emoji ngoài các mục đã quy định.
""".strip()


# ====================== SCHEMA & DB HELPERS ======================
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
    """
    Kết nối SQLite và đảm bảo schema sẵn sàng.
    - TÔN TRỌNG tham số db_path (không hard-code).
    - Đảm bảo thư mục chứa DB tồn tại.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def upsert_prompt(
    conn: sqlite3.Connection,
    key: str,
    profile: str,
    content: str,
    meta: dict | None = None,
    version: int | None = None
) -> int:
    """
    Tạo phiên bản mới cho key nếu version=None, hoặc chèn đúng version truyền vào.
    """
    if version is None:
        cur = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM prompts WHERE key=?", (key,))
        (version,) = cur.fetchone()

    conn.execute(
        """
        INSERT INTO prompts(key, profile, version, content, meta, created_at, updated_at)
        VALUES(?,?,?,?,json(?),datetime('now'),datetime('now'))
        """,
        (key, profile, version, content, json.dumps(meta or {}))
    )
    conn.commit()
    return version

def get_prompt(conn: sqlite3.Connection, key: str, version: int | None = None):
    """
    Lấy prompt theo key; nếu không truyền version sẽ lấy bản mới nhất.
    """
    if version is None:
        row = conn.execute(
            "SELECT content, COALESCE(meta,'{}') FROM prompts WHERE key=? ORDER BY version DESC LIMIT 1",
            (key,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT content, COALESCE(meta,'{}') FROM prompts WHERE key=? AND version=?",
            (key, version)
        ).fetchone()

    if not row:
        return None
    content, meta = row
    return content, json.loads(meta)

def seed_defaults_if_empty() -> None:
    """
    Seed 2 prompt mặc định nếu chưa có:
    - system:Accountant (profile=Accountant)
    - system:GENERIC   (profile=GENERIC)
    """
    conn = connect()
    try:
        row = conn.execute("SELECT 1 FROM prompts WHERE key='system:Accountant' LIMIT 1").fetchone()
        if not row:
            upsert_prompt(
                conn,
                key="system:Accountant",
                profile="Accountant",
                content=ACCOUNTANT_SYSTEM_PROMPT.strip(),
                meta={"tone": ACCOUNTANT_TONE, "output": ACCOUNTANT_OUTPUT},
            )

        row = conn.execute("SELECT 1 FROM prompts WHERE key='system:GENERIC' LIMIT 1").fetchone()
        if not row:
            upsert_prompt(
                conn,
                key="system:GENERIC",
                profile="GENERIC",
                content=GENERIC_SYSTEM_PROMPT.strip(),
                meta={"lang": "vi"},
            )
    finally:
        conn.close()

def get_system_prompt(profile: str = "Accountant") -> str:
    """
    Lấy prompt hệ thống theo profile.
    - Nếu không có trong DB, trả về prompt mặc định trong file.
    """
    key = "system:Accountant" if (profile or "").upper() == "ACCOUNTANT" else "system:GENERIC"
    conn = connect()
    try:
        row = get_prompt(conn, key)
        if row:
            content, _meta = row
            return content
        # fallback khi chưa seed
        return ACCOUNTANT_SYSTEM_PROMPT if key == "system:Accountant" else GENERIC_SYSTEM_PROMPT
    finally:
        conn.close()

# ============== Nếu chạy file trực tiếp: seed nhanh và in xác nhận ==============
if __name__ == "__main__":
    seed_defaults_if_empty()
    print("[prompts_accountant] Seed mặc định hoàn tất. Ví dụ lấy prompt Accountant:")
    print("=" * 80)
    print(get_system_prompt("Accountant"))
    print("=" * 80)
