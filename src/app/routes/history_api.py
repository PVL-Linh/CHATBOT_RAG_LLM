# from __future__ import annotations
# import os, sqlite3, uuid, io, csv, json as _json, re, hashlib
# from datetime import datetime, timezone
# from zoneinfo import ZoneInfo
# from flask import Blueprint, jsonify, request, session
# from app.config.paths import USER_CHAT_ALL
# try:
#     from app.Login.login_required import login_required
# except Exception:
#     from app.Login.login_required import login_required
# from app.config.settings import ChatConfig
# bp = Blueprint("history_api", __name__)

# # =======================
# # Config
# # =======================
# MAX_HISTORY   = ChatConfig.MAX_HISTORY
# LOCAL_TZ_NAME = ChatConfig.LOCAL_TZ_NAME

# # =======================
# # DB helpers
# # =======================
# def _conn():
#     os.makedirs(os.path.dirname(USER_CHAT_ALL) or ".", exist_ok=True)
#     con = sqlite3.connect(USER_CHAT_ALL, timeout=30, check_same_thread=False)
#     con.execute("PRAGMA journal_mode=WAL;")
#     con.execute("PRAGMA synchronous=NORMAL;")
#     con.execute("PRAGMA busy_timeout=5000;")
#     con.execute("PRAGMA foreign_keys=ON;")
#     return con

# # ========== USER -> TABLE NAMES (an toàn) ==========
# _slug_re = re.compile(r"[^a-z0-9_]+")

# def _user_slug(username: str) -> str:
#     base = (_slug_re.sub("_", (username or "").strip().lower())).strip("_")
#     if not base or base in {"sqlite_master", "sqlite_temp_master"}:
#         base = "u_" + hashlib.sha1((username or "").encode("utf-8")).hexdigest()[:10]
#     return base

# def _tables(username: str) -> tuple[str, str, str]:
#     slug = _user_slug(username)
#     return slug, f"chat_{slug}_sessions", f"chat_{slug}_messages"

# def _ensure_user_schema(username: str):
#     """Tạo 2 bảng riêng cho user nếu chưa có."""
#     slug, s_table, m_table = _tables(username)
#     con = _conn()
#     try:
#         con.execute(f"""
#             CREATE TABLE IF NOT EXISTS {s_table}(
#               id         TEXT PRIMARY KEY,
#               title      TEXT DEFAULT 'Cuộc trò chuyện',
#               created_at TEXT NOT NULL,
#               updated_at TEXT NOT NULL
#             );
#         """)
#         con.execute(f"""
#             CREATE TABLE IF NOT EXISTS {m_table}(
#               id         INTEGER PRIMARY KEY AUTOINCREMENT,
#               session_id TEXT NOT NULL,
#               role       TEXT NOT NULL,   -- 'user' | 'assistant' | ...
#               content    TEXT NOT NULL,
#               ts_utc     TEXT NOT NULL,
#               ts_local   TEXT NOT NULL,
#               FOREIGN KEY(session_id) REFERENCES {s_table}(id) ON DELETE CASCADE
#             );
#         """)
#         con.execute(f"CREATE INDEX IF NOT EXISTS idx_{slug}_sid_ts ON {m_table}(session_id, ts_utc);")
#         con.execute(f"CREATE INDEX IF NOT EXISTS idx_{slug}_ts     ON {m_table}(ts_utc);")
#         con.commit()
#     finally:
#         con.close()

# def _session_exists(username: str, session_id: str) -> bool:
#     if not username or not session_id:
#         return False
#     _ensure_user_schema(username)
#     _, s_table, _ = _tables(username)
#     con = _conn()
#     try:
#         cur = con.execute(f"SELECT 1 FROM {s_table} WHERE id=?", (session_id,))
#         return cur.fetchone() is not None
#     finally:
#         con.close()

# # =======================
# # Time helpers
# # =======================
# def _now_pair(ts_utc_iso: str | None = None) -> tuple[str, str]:
#     try:
#         ts_utc = datetime.fromisoformat((ts_utc_iso or "").replace("Z", "+00:00"))
#     except Exception:
#         ts_utc = datetime.now(timezone.utc)
#     ts_utc_iso = ts_utc.isoformat()
#     try:
#         local_tz = ZoneInfo(LOCAL_TZ_NAME)
#     except Exception:
#         local_tz = timezone.utc
#     ts_local_iso = ts_utc.astimezone(local_tz).isoformat()
#     return ts_utc_iso, ts_local_iso

# def _ts_now() -> str:
#     return datetime.now(timezone.utc).isoformat()

# # =======================
# # Session helpers (per-user tables)
# # =======================
# def _generate_sid() -> str:
#     ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
#     return f"s-{ts}-{uuid.uuid4().hex[:8]}"

# def _latest_or_create_session_id(username: str) -> str:
#     _ensure_user_schema(username)
#     _, s_table, _ = _tables(username)
#     con = _conn()
#     try:
#         cur = con.execute(f"SELECT id FROM {s_table} ORDER BY updated_at DESC LIMIT 1")
#         row = cur.fetchone()
#         if row:
#             return row[0]
#         sid = _generate_sid()
#         now = _ts_now()
#         con.execute(
#             f"INSERT INTO {s_table}(id,title,created_at,updated_at) VALUES(?,?,?,?)",
#             (sid, "Mặc định", now, now)
#         )
#         con.commit()
#         return sid
#     finally:
#         con.close()

# def create_new_session(username: str, title: str | None = None) -> dict:
#     _ensure_user_schema(username)
#     _, s_table, _ = _tables(username)
#     sid = _generate_sid()
#     now = _ts_now()
#     con = _conn()
#     try:
#         con.execute(
#             f"INSERT INTO {s_table}(id,title,created_at,updated_at) VALUES(?,?,?,?)",
#             (sid, (title or "Cuộc trò chuyện"), now, now)
#         )
#         con.commit()
#     finally:
#         con.close()
#     return {"session_id": sid, "title": title or "Cuộc trò chuyện", "created_at": now}

# def rename_session(username: str, session_id: str, new_title: str) -> bool:
#     _ensure_user_schema(username)
#     _, s_table, _ = _tables(username)
#     con = _conn()
#     try:
#         cur = con.execute(f"SELECT id FROM {s_table} WHERE id=?", (session_id,))
#         if not cur.fetchone():
#             return False
#         con.execute(
#             f"UPDATE {s_table} SET title=?, updated_at=? WHERE id=?",
#             (new_title or "Cuộc trò chuyện", _ts_now(), session_id)
#         )
#         con.commit()
#         return True
#     finally:
#         con.close()

# def delete_session(username: str, session_id: str) -> bool:
#     """
#     Xóa 1 phiên và toàn bộ tin nhắn thuộc phiên đó (ON DELETE CASCADE).
#     """
#     if not username or not session_id:
#         return False
#     _ensure_user_schema(username)
#     _, s_table, _ = _tables(username)
#     con = _conn()
#     try:
#         cur = con.execute(f"DELETE FROM {s_table} WHERE id=?", (session_id,))
#         con.commit()
#         return cur.rowcount > 0
#     finally:
#         con.close()

# # =======================
# # Log helpers (stateless, per-user tables)
# # =======================
# def log_message(username: str, role: str, content: str, ts_utc_iso: str | None, maybe_session_id: str | None):
#     if not username:
#         return None
#     _ensure_user_schema(username)
#     slug, s_table, m_table = _tables(username)

#     sid = (maybe_session_id or "").strip()
#     con = _conn()
#     try:
#         if not sid:
#             if (role or "").lower() == "user":
#                 # user message đầu tiên mà thiếu sid -> tạo phiên mới
#                 sid = _generate_sid()
#                 now = _ts_now()
#                 con.execute(
#                     f"INSERT INTO {s_table}(id,title,created_at,updated_at) VALUES(?,?,?,?)",
#                     (sid, "Cuộc trò chuyện", now, now)
#                 )
#             else:
#                 # assistant -> lấy phiên gần nhất hoặc tạo mặc định
#                 cur = con.execute(f"SELECT id FROM {s_table} ORDER BY updated_at DESC LIMIT 1")
#                 row = cur.fetchone()
#                 if row:
#                     sid = row[0]
#                 else:
#                     sid = _generate_sid()
#                     now = _ts_now()
#                     con.execute(
#                         f"INSERT INTO {s_table}(id,title,created_at,updated_at) VALUES(?,?,?,?)",
#                         (sid, "Mặc định", now, now)
#                     )

#         # đảm bảo session tồn tại
#         cur = con.execute(f"SELECT id FROM {s_table} WHERE id=?", (sid,))
#         if not cur.fetchone():
#             now = _ts_now()
#             con.execute(
#                 f"INSERT INTO {s_table}(id,title,created_at,updated_at) VALUES(?,?,?,?)",
#                 (sid, "Cuộc trò chuyện", now, now)
#             )

#         ts_utc, ts_local = _now_pair(ts_utc_iso)
#         con.execute(
#             f"INSERT INTO {m_table}(session_id, role, content, ts_utc, ts_local) VALUES(?,?,?,?,?)",
#             (sid, role, content or "", ts_utc, ts_local)
#         )

#         # cập nhật title từ câu user đầu tiên; luôn cập nhật updated_at
#         if role == "user":
#             cur = con.execute(f"SELECT title FROM {s_table} WHERE id=?", (sid,))
#             title = (cur.fetchone() or [""])[0] or ""
#             if title in ("", "Mặc định", "Cuộc trò chuyện"):
#                 new_title = (content or "")[:30] or "Cuộc trò chuyện"
#                 con.execute(f"UPDATE {s_table} SET title=?, updated_at=? WHERE id=?", (new_title, ts_utc, sid))
#             else:
#                 con.execute(f"UPDATE {s_table} SET updated_at=? WHERE id=?", (ts_utc, sid))
#         else:
#             con.execute(f"UPDATE {s_table} SET updated_at=? WHERE id=?", (ts_utc, sid))

#         con.commit()
#         return sid
#     finally:
#         con.close()

# # =======================
# # Read helpers (per-user tables)
# # =======================
# def read_sessions_and_messages(username: str) -> dict[str, list[dict]]:
#     """Trả về {session_id: [ {role, content, ts}, ... ]} cho user."""
#     _ensure_user_schema(username)
#     _, _, m_table = _tables(username)
#     con = _conn()
#     try:
#         sessions = {}
#         cur = con.execute(
#             f"SELECT session_id, role, content, ts_utc FROM {m_table} ORDER BY ts_utc ASC"
#         )
#         for sid, role, content, ts_utc in cur.fetchall():
#             sessions.setdefault(sid, []).append({
#                 "role": role, "content": content, "ts": ts_utc
#             })
#         return sessions
#     finally:
#         con.close()

# def list_user_sessions(username: str):
#     """Trả danh sách meta {id, title, count, first_ts, last_ts} cho user."""
#     _ensure_user_schema(username)
#     _, s_table, m_table = _tables(username)
#     con = _conn()
#     try:
#         # LEFT JOIN để có cả session chưa có message
#         cur = con.execute(f"""
#             SELECT
#               s.id,
#               s.title,
#               COALESCE(a.cnt, 0)      as count,
#               COALESCE(a.first_ts, '') as first_ts,
#               COALESCE(a.last_ts,  s.updated_at) as last_ts
#             FROM {s_table} s
#             LEFT JOIN (
#               SELECT session_id, COUNT(*) as cnt, MIN(ts_utc) as first_ts, MAX(ts_utc) as last_ts
#               FROM {m_table}
#               GROUP BY session_id
#             ) a ON a.session_id = s.id
#             ORDER BY last_ts DESC
#         """)
#         out = []
#         for sid, title, cnt, first_ts, last_ts in cur.fetchall():
#             out.append({
#                 "id": sid,
#                 "title": title or "Cuộc trò chuyện",
#                 "count": cnt,
#                 "first_ts": first_ts,
#                 "last_ts": last_ts,
#             })
#         return out
#     finally:
#         con.close()

# # =======================
# # Export helpers (per-user tables)
# # =======================
# def _fetch_messages(username: str, session_id: str | None = None,
#                     date_from: str | None = None, date_to: str | None = None):
#     _ensure_user_schema(username)
#     _, _, m_table = _tables(username)

#     q, args = [], []
#     if session_id:
#         q.append("session_id=?")
#         args.append(session_id)
#     if date_from:
#         q.append("ts_utc >= ?")
#         args.append(f"{date_from}T00:00:00+00:00")
#     if date_to:
#         q.append("ts_utc < ?")
#         args.append(f"{date_to}T00:00:00+00:00")

#     where = ("WHERE " + " AND ".join(q)) if q else ""
#     sql = f"""
#         SELECT session_id, role, content, ts_utc, ts_local
#         FROM {m_table}
#         {where}
#         ORDER BY ts_utc ASC
#     """
#     con = _conn()
#     try:
#         cur = con.execute(sql, tuple(args))
#         rows = cur.fetchall()
#         return [{
#             "session_id": sid, "role": role, "content": content,
#             "ts_utc": ts_utc, "ts_local": ts_local
#         } for (sid, role, content, ts_utc, ts_local) in rows]
#     finally:
#         con.close()

# def _filename_for_export(username: str, session_id: str | None, ext: str):
#     ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
#     base = f"chat_export_{_user_slug(username)}_{ts}"
#     if session_id:
#         base += f"_{session_id[:12]}"
#     return f"{base}.{ext}"

# # =======================
# # API endpoints
# # =======================
# @bp.route("/api/history", methods=["GET"])
# @login_required(api=True)
# def api_history():
#     user = session.get("user")
#     if not user:
#         return jsonify({"items": []})
#     limit = int(request.args.get("limit", 50))
#     sessions = read_sessions_and_messages(user)
#     flat = []
#     for sid, msgs in sessions.items():
#         for m in msgs:
#             flat.append({**m, "session_id": sid})
#     flat.sort(key=lambda x: x.get("ts") or "")
#     return jsonify({"items": flat[-min(limit, MAX_HISTORY):]})

# @bp.route("/api/history/sessions", methods=["GET"])
# @login_required(api=True)
# def api_history_sessions():
#     user = session.get("user")
#     if not user:
#         return jsonify({"sessions": []})
#     metas = list_user_sessions(user)
#     return jsonify({"sessions": metas})

# @bp.route("/api/history/by_session", methods=["GET"])
# @login_required(api=True)
# def api_history_by_session():
#     """
#     Lấy tin nhắn theo 1 session cụ thể.
#     - Nếu không truyền session_id hoặc session_id không tồn tại -> trả về phiên mới nhất hoặc tạo mới.
#     """
#     user = session.get("user")
#     if not user:
#         return jsonify({"items": []})

#     req_sid = (request.args.get("session_id") or "").strip()

#     # Nếu có sid nhưng không tồn tại → chuyển sang phiên hợp lệ
#     if not req_sid or not _session_exists(user, req_sid):
#         sid = _latest_or_create_session_id(user)
#         items = _fetch_messages(user, session_id=sid)
#         return jsonify({"items": items, "session_id": sid})

#     # Có sid và tồn tại
#     items = _fetch_messages(user, session_id=req_sid)
#     return jsonify({"items": items, "session_id": req_sid})

# @bp.route("/api/history/new_session", methods=["POST"])
# @login_required(api=True)
# def api_new_session():
#     user = session.get("user")
#     if not user:
#         return jsonify({"error": "Unauthorized"}), 401
#     title = (request.json or {}).get("title") if request.is_json else request.form.get("title")
#     info = create_new_session(user, title=title)
#     return jsonify(info), 201

# @bp.route("/api/history/rename_session", methods=["POST"])
# @login_required(api=True)
# def api_rename_session():
#     user = session.get("user")
#     if not user:
#         return jsonify({"error": "Unauthorized"}), 401
#     payload = request.get_json(silent=True) or {}
#     sid = (payload.get("session_id") or "").strip()
#     title = (payload.get("title") or "").strip()
#     if not sid or not title:
#         return jsonify({"error": "session_id and title required"}), 400
#     ok = rename_session(user, sid, title)
#     return jsonify({"ok": bool(ok)}), (200 if ok else 404)

# @bp.route("/api/history/delete_session", methods=["POST"])
# @login_required(api=True)
# def api_delete_session():
#     """
#     Xóa 1 phiên và toàn bộ tin nhắn trong DB (ON DELETE CASCADE).
#     """
#     user = session.get("user")
#     if not user:
#         return jsonify({"error": "Unauthorized"}), 401
#     payload = request.get_json(silent=True) or {}
#     sid = (payload.get("session_id") or "").strip()
#     if not sid:
#         return jsonify({"error": "session_id required"}), 400
#     ok = delete_session(user, sid)
#     return jsonify({"ok": bool(ok)}), (200 if ok else 404)

# @bp.route("/api/history/clear_user", methods=["POST"])
# @login_required(api=True)
# def api_clear_user():
#     """
#     Xóa toàn bộ lịch sử (sessions + messages) của user hiện tại.
#     """
#     user = session.get("user")
#     if not user:
#         return jsonify({"error": "Unauthorized"}), 401
#     _ensure_user_schema(user)
#     _, s_table, m_table = _tables(user)
#     con = _conn()
#     try:
#         con.execute(f"DELETE FROM {m_table}")
#         con.execute(f"DELETE FROM {s_table}")
#         con.commit()
#         return jsonify({"ok": True})
#     finally:
#         con.close()

# @bp.route("/api/history/export", methods=["GET"])
# @login_required(api=True)
# def api_history_export():
#     """
#     Xuất tin nhắn:
#       - format: 'json' (mặc định) hoặc 'csv'
#       - session_id: (optional) chỉ 1 phiên
#       - date_from, date_to: (optional) 'YYYY-MM-DD' UTC
#     """
#     user = session.get("user")
#     if not user:
#         return jsonify({"error": "Unauthorized"}), 401

#     fmt = (request.args.get("format") or "json").lower().strip()
#     sid = (request.args.get("session_id") or "").strip() or None
#     date_from = (request.args.get("date_from") or "").strip() or None
#     date_to   = (request.args.get("date_to") or "").strip() or None

#     items = _fetch_messages(user, sid, date_from, date_to)

#     if fmt == "csv":
#         buff = io.StringIO(newline="")
#         writer = csv.writer(buff)
#         writer.writerow(["session_id", "role", "content", "ts_utc", "ts_local"])
#         for it in items:
#             writer.writerow([it["session_id"], it["role"], it["content"], it["ts_utc"], it["ts_local"]])
#         csv_data = buff.getvalue(); buff.close()
#         filename = _filename_for_export(user, sid, "csv")
#         resp = bp.response_class(response=csv_data, status=200, mimetype="text/csv; charset=utf-8")
#         resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
#         resp.headers["Cache-Control"] = "no-cache"
#         return resp

#     # JSON (default)
#     json_text = _json.dumps(items, ensure_ascii=False, indent=2)
#     filename = _filename_for_export(user, sid, "json")
#     resp = bp.response_class(response=json_text, status=200, mimetype="application/json; charset=utf-8")
#     resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
#     resp.headers["Cache-Control"] = "no-cache"
#     return resp

from __future__ import annotations
import os
import uuid
import sqlite3
import json as _json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request, session
from dotenv import load_dotenv

from app.config.settings import ChatConfig
from app.config.paths import USER_CHAT_ALL
try:
    from app.Login.login_required import login_required
except Exception:
    from app.Login.login_required import login_required

load_dotenv()

bp = Blueprint("history_api", __name__)

# =======================
# Config
# =======================
MAX_HISTORY = ChatConfig.MAX_HISTORY
LOCAL_TZ_NAME = ChatConfig.LOCAL_TZ_NAME
DEFAULT_PAGE_SIZE = 100

# =======================
# SQLite connection
# =======================
DB_PATH = str(USER_CHAT_ALL)


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Một số pragma cơ bản
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _ensure_schema() -> None:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        # Bảng sessions
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # Bảng messages
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts_utc TEXT NOT NULL,
                ts_local TEXT NOT NULL,
                model TEXT,
                metadata TEXT,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, ts_utc);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id, updated_at);"
        )
        conn.commit()
    finally:
        conn.close()


_ensure_schema()


# =======================
# Helper functions
# =======================
def _now_pair(ts_utc_iso: str | None = None) -> tuple[str, str]:
    try:
        ts_utc = datetime.fromisoformat((ts_utc_iso or "").replace("Z", "+00:00"))
    except Exception:
        ts_utc = datetime.now(timezone.utc)
    ts_utc_iso = ts_utc.isoformat(timespec="seconds")
    try:
        local_tz = ZoneInfo(LOCAL_TZ_NAME)
    except Exception:
        local_tz = timezone.utc
    ts_local_iso = ts_utc.astimezone(local_tz).isoformat(timespec="seconds")
    return ts_utc_iso, ts_local_iso


def _ts_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generate_sid() -> str:
    """Tạo session_id chuẩn UUID v4"""
    return str(uuid.uuid4())


def _get_current_user_id() -> str | None:
    return session.get("user")


def validate_and_fix_session_id(session_id: str | None) -> str:
    """
    Kiểm tra session_id có phải UUID hợp lệ không.
    Nếu sai hoặc None → tạo mới.
    """
    if not session_id:
        return _generate_sid()

    try:
        uuid.UUID(session_id)
        return session_id
    except ValueError:
        print(f"[Warning] Session ID không hợp lệ: '{session_id}' → tạo mới")
        return _generate_sid()


# =======================
# Core functions (SQLite)
# =======================
def log_message(
    role: str,
    content: str,
    session_id: str | None = None,
    model: str | None = None,
    metadata: dict | None = None,
) -> str:
    """
    Ghi 1 message vào SQLite, giữ nguyên API như bản Supabase.
    """
    user_id = _get_current_user_id()
    if not user_id:
        raise ValueError("User not authenticated")

    sid = validate_and_fix_session_id(session_id)
    ts_utc, ts_local = _now_pair(None)
    metadata_json = _json.dumps(metadata) if metadata else None

    conn = _get_conn()
    try:
        cur = conn.cursor()
        # BƯỚC 1: Kiểm tra và tạo session nếu chưa có
        cur.execute(
            "SELECT title FROM chat_sessions WHERE id = ? AND user_id = ?",
            (sid, user_id),
        )
        row = cur.fetchone()

        if not row:
            title = (
                content[:50].strip() or "Cuộc trò chuyện"
                if role == "user"
                else "Cuộc trò chuyện"
            )
            cur.execute(
                """
                INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, user_id, title, ts_utc, ts_utc),
            )
        else:
            current_title = row["title"]
            if role == "user" and current_title in ("Cuộc trò chuyện", "Mặc định", ""):
                new_title = content[:50].strip() or current_title
                cur.execute(
                    """
                    UPDATE chat_sessions SET title = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (new_title, ts_utc, sid, user_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE chat_sessions SET updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (ts_utc, sid, user_id),
                )

        # BƯỚC 2: Insert message
        cur.execute(
            """
            INSERT INTO chat_messages (
                session_id, user_id, role, content, ts_utc, ts_local, model, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sid, user_id, role, content or "", ts_utc, ts_local, model, metadata_json),
        )

        conn.commit()
        return sid
    except Exception as e:
        conn.rollback()
        print(f"[History] Error in log_message: {e}")
        raise
    finally:
        conn.close()


def get_session_messages(
    session_id: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> list[dict]:
    user_id = _get_current_user_id()
    if not user_id:
        return []

    session_id = validate_and_fix_session_id(session_id)

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM chat_messages
            WHERE user_id = ? AND session_id = ?
            ORDER BY ts_utc ASC
            LIMIT ? OFFSET ?
            """,
            (user_id, session_id, limit, offset),
        )
        rows = cur.fetchall()

        result = []
        for row in rows:
            item = dict(row)
            if item.get("metadata"):
                try:
                    item["metadata"] = _json.loads(item["metadata"])
                except Exception:
                    item["metadata"] = None
            result.append(item)
        return result
    except Exception as e:
        print(f"[History] Error fetching messages: {e}")
        return []
    finally:
        conn.close()


def list_user_sessions() -> list[dict]:
    user_id = _get_current_user_id()
    if not user_id:
        return []

    conn = _get_conn()
    try:
        cur = conn.cursor()
        # SQLite không có LATERAL, dùng subquery để lấy last message
        cur.execute(
            """
            SELECT
                s.id,
                s.title,
                s.created_at,
                s.updated_at,
                COUNT(m.id) AS message_count,
                (
                    SELECT content
                    FROM chat_messages m2
                    WHERE m2.session_id = s.id AND m2.user_id = s.user_id
                    ORDER BY m2.ts_utc DESC
                    LIMIT 1
                ) AS last_content,
                (
                    SELECT role
                    FROM chat_messages m2
                    WHERE m2.session_id = s.id AND m2.user_id = s.user_id
                    ORDER BY m2.ts_utc DESC
                    LIMIT 1
                ) AS last_role
            FROM chat_sessions s
            LEFT JOIN chat_messages m
                ON m.session_id = s.id AND m.user_id = s.user_id
            WHERE s.user_id = ?
            GROUP BY s.id, s.title, s.created_at, s.updated_at
            ORDER BY s.updated_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()

        sessions = []
        for row in rows:
            preview = None
            if row["last_content"]:
                text = str(row["last_content"])[:80]
                if len(str(row["last_content"])) > 80:
                    text += "..."
                preview = {"role": row["last_role"], "content": text}

            sessions.append(
                {
                    "id": row["id"],
                    "title": row["title"] or "Cuộc trò chuyện",
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "message_count": row["message_count"] or 0,
                    "preview": preview,
                }
            )
        return sessions
    except Exception as e:
        print(f"[History] Error listing sessions: {e}")
        return []
    finally:
        conn.close()


def create_new_session(title: str | None = None) -> dict:
    user_id = _get_current_user_id()
    if not user_id:
        raise ValueError("Unauthorized")

    sid = _generate_sid()
    now = _ts_now()
    session_title = title or "Cuộc trò chuyện"

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sid, user_id, session_title, now, now),
        )
        conn.commit()
        return {"session_id": sid, "title": session_title}
    except Exception as e:
        conn.rollback()
        print(f"[History] Error creating session: {e}")
        raise
    finally:
        conn.close()


def rename_session(session_id: str, new_title: str) -> bool:
    user_id = _get_current_user_id()
    if not user_id:
        return False

    session_id = validate_and_fix_session_id(session_id)

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_sessions SET title = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (new_title or "Cuộc trò chuyện", _ts_now(), session_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        print(f"[History] Error renaming session: {e}")
        return False
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    user_id = _get_current_user_id()
    if not user_id:
        return False

    session_id = validate_and_fix_session_id(session_id)

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        print(f"[History] Error deleting session: {e}")
        return False
    finally:
        conn.close()


# =======================
# API Endpoints
# =======================
@bp.route("/api/history/sessions", methods=["GET"])
@login_required(api=True)
def api_history_sessions():
    return jsonify({"sessions": list_user_sessions()})


@bp.route("/api/history/by_session", methods=["GET"])
@login_required(api=True)
def api_history_by_session():
    req_sid = request.args.get("session_id", "").strip()
    req_sid = validate_and_fix_session_id(req_sid)
    limit = min(int(request.args.get("limit", DEFAULT_PAGE_SIZE)), 500)
    offset = int(request.args.get("offset", 0))

    if not req_sid:
        # Nếu không có session_id, tạo phiên mới
        req_sid = create_new_session()["session_id"]

    items = get_session_messages(req_sid, limit=limit, offset=offset)

    return jsonify(
        {
            "items": items,
            "session_id": req_sid,
            "has_more": len(items) == limit,
        }
    )


@bp.route("/api/history/new_session", methods=["POST"])
@login_required(api=True)
def api_new_session():
    title = (request.get_json(silent=True) or {}).get("title") or request.form.get("title")
    info = create_new_session(title)
    return jsonify(info), 201


@bp.route("/api/history/rename_session", methods=["POST"])
@login_required(api=True)
def api_rename_session():
    payload = request.get_json(silent=True) or {}
    sid = payload.get("session_id", "").strip()
    title = payload.get("title", "").strip()
    if not sid or not title:
        return jsonify({"error": "Missing params"}), 400
    ok = rename_session(sid, title)
    return jsonify({"ok": ok}), (200 if ok else 404)


@bp.route("/api/history/delete_session", methods=["POST"])
@login_required(api=True)
def api_delete_session():
    payload = request.get_json(silent=True) or {}
    sid = payload.get("session_id", "").strip()
    if not sid:
        return jsonify({"error": "session_id required"}), 400
    ok = delete_session(sid)
    return jsonify({"ok": ok}), (200 if ok else 404)