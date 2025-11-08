# app/routes/hr_rag.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import time
import sqlite3
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, Optional, List

from flask import (
    Blueprint,
    request,
    jsonify,
    Response,
    stream_with_context,
    session,
)

# ---------------- Optional login_required ----------------
try:
    from app.Login.login_required import login_required
except Exception:  # pragma: no cover
    def login_required(fn):  # type: ignore
        return fn
    # ---------------- Accountant RAG engine (fallback) ----------------
# ---------------- Accountant RAG engine (fallback) ----------------
try:
    from app.rag_accountant.engine_accountant import answer_with_rag_accountant, build_lex_query_accountant
except Exception as e:  # pragma: no cover
    import sys, traceback
    print("[Accountant] Import engine failed:", e, file=sys.stderr)
    traceback.print_exc()

    def answer_with_rag_accountant(q: str):
        return ("Engine Accountant chưa sẵn sàng. Vui lòng cấu hình app.rag_hr.engine_accountant", {"hits": []})
    def build_lex_query_accountant(q: str):
        return {"lex_query": q, "canonical": q}


# ======================= DATABASE =========================
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Data_app", "chat_accountant.db"))

def _ensure_dir_exists(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def _get_conn() -> sqlite3.Connection:
    _ensure_dir_exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return conn

def init_accountant_db() -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accountant_sessions (
            id TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            title TEXT DEFAULT 'Cuộc trò chuyện Accountant',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accountant_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES accountant_sessions(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_accountant_messages_session ON accountant_messages(session_id, timestamp)""")
    conn.commit()
    conn.close()

init_accountant_db()

# ======================== HELPERS =========================
def _get_user() -> str:
    return session.get("user") or "anonymous"

def _trim(s: str, n: int = 8000) -> str:
    s = (s or "").strip()
    return (s[:n] + "…") if len(s) > n else s

def _json_error(msg: str, code: int = 400, **extra):
    p = {"error": msg}
    if extra:
        p.update(extra)
    return jsonify(p), code

# ---------- SQL helpers ----------
def create_accountant_session(user: str = "", title: str = "Cuộc trò chuyện Accountant") -> str:
    sid = str(uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO accountant_sessions (id, user, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (sid, user or "anonymous", title, now, now),
    )
    conn.commit()
    conn.close()
    return sid

def add_accountant_message(session_id: str, role: str, content: str) -> None:
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO accountant_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now),
    )
    cur.execute("UPDATE accountant_sessions SET updated_at=? WHERE id=?", (now, session_id))
    conn.commit()
    conn.close()

def get_accountant_sessions_list(user: str, limit: int = 200) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.title, s.created_at, s.updated_at,
               (SELECT content FROM accountant_messages
                WHERE session_id=s.id AND role='user'
                ORDER BY timestamp ASC LIMIT 1) AS preview
        FROM accountant_sessions s
        WHERE s.user=?
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (user, limit))
    out = [{
        "id": r[0], "title": r[1], "first_ts": r[2], "last_ts": r[3], "preview": (r[4] or "")[:100]
    } for r in cur.fetchall()]
    conn.close()
    return out

def get_accountant_session_messages(session_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT role, content, timestamp AS ts FROM accountant_messages WHERE session_id=? ORDER BY timestamp ASC",
                (session_id,))
    out = [dict(r) for r in cur.fetchall()]
    conn.close()
    return out

def rename_accountant_session(session_id: str, title: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE accountant_sessions SET title=?, updated_at=? WHERE id=?",
                (title, datetime.utcnow().isoformat(), session_id))
    conn.commit()
    conn.close()

def delete_accountant_session(session_id: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM accountant_messages WHERE session_id=?", (session_id,))
    cur.execute("DELETE FROM accountant_sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()

def get_latest_accountant_session(user: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM accountant_sessions WHERE user=? ORDER BY updated_at DESC LIMIT 1", (user,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    sid = row[0]
    messages = get_accountant_session_messages(sid)
    conn.close()
    return {"session_id": sid, "items": messages}

# ---------- New: ownership/existence checks ----------
def _get_session_owner(session_id: str) -> Optional[str]:
    if not session_id:
        return None
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user FROM accountant_sessions WHERE id=?", (session_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def _ensure_valid_or_create_session(session_id: str, user: str, title: str) -> str:
    """
    - Không có session_id  -> tạo mới.
    - Có session_id nhưng không tồn tại -> tạo mới.
    - Có session_id của user khác -> 403 (raise).
    - Có session_id đúng user -> dùng lại.
    """
    if not session_id:
        return create_accountant_session(user=user, title=title)

    owner = _get_session_owner(session_id)
    if owner is None:
        # client gửi id local tự phát -> tạo server session mới
        return create_accountant_session(user=user, title=title)
    if owner != user:
        # gửi nhầm id của user khác
        raise PermissionError("Forbidden: session does not belong to current user")
    return session_id

# ======================= BLUEPRINTS =======================
bp_accountant_rag = Blueprint("accountant_rag", __name__, url_prefix="/api/accountant")
bp_accountant_history = Blueprint("accountant_history", __name__, url_prefix="/api/history/accountant")

__all__ = ["bp_accountant_rag", "bp_accountant_history"]

# =================== RAG / QA ENDPOINTS ===================
_INBOX: Dict[str, Dict[str, Any]] = {}
_PROCESSED: Dict[str, Dict[str, Any]] = {}

@bp_accountant_rag.post("/receive")
@login_required
def receive_message():
    data = request.get_json(silent=True) or {}
    question = _trim(str(data.get("question", "")))
    if not question:
        return _json_error("Thiếu 'question'.")
    msg_id = str(uuid4())
    _INBOX[msg_id] = {
        "question": question,
        "user_id": data.get("user_id"),
        "channel": data.get("channel"),
        "metadata": data.get("metadata") or {},
        "status": "received",
    }
    return jsonify({"message_id": msg_id, "status": "received"}), 201

@bp_accountant_rag.post("/reply")
@login_required
def reply_message():
    data = request.get_json(silent=True) or {}
    msg_id = (data.get("message_id") or "").strip()
    direct_question = _trim(str(data.get("question", "")))

    if msg_id:
        record = _INBOX.get(msg_id)
        if not record:
            processed = _PROCESSED.get(msg_id)
            if processed:
                return jsonify({
                    "message_id": msg_id,
                    "status": "already_answered",
                    "question": processed.get("question"),
                    "answer": processed.get("answer"),
                    "trace": processed.get("trace"),
                    "debug": processed.get("debug"),
                })
            print("[DBG] Returning already answered for msg_id", msg_id)
            return _json_error(f"message_id '{msg_id}' không tồn tại", 404)

        q = (record.get("question") or "").strip() or direct_question
        if not q:
            return _json_error("Câu hỏi trống.")

        try:
            lexinfo = build_lex_query_accountant(q)
            answer, trace = answer_with_rag_accountant(q)
            record["status"] = "answered"
            debug = {
                "expanded_query": lexinfo.get("lex_query"),
                "canonical": lexinfo.get("canonical"),
            }
            _PROCESSED[msg_id] = {**record, "question": q, "answer": answer, "trace": trace, "debug": debug}
            _INBOX.pop(msg_id, None)
            return jsonify({
                "message_id": msg_id,
                "question": q,
                "answer": answer,
                "trace": trace,
                "debug": debug
            })
        except Exception as e:
            record["status"] = "error"
            return _json_error(str(e), 500, message_id=msg_id)

    if not direct_question:
        return _json_error("Thiếu 'message_id' hoặc 'question'.")

    try:
        lexinfo = build_lex_query_accountant(direct_question)
        answer, trace = answer_with_rag_accountant(direct_question)
        debug = {
            "expanded_query": lexinfo.get("lex_query"),
            "canonical": lexinfo.get("canonical"),
        }
        return jsonify({"question": direct_question, "answer": answer, "trace": trace, "debug": debug})
    except Exception as e:
        return _json_error(str(e), 500)

@bp_accountant_rag.post("/ask")
@login_required
def ask_direct():
    data = request.get_json(silent=True) or {}
    q = _trim(str(data.get("question", "")))
    if not q:
        return _json_error("Thiếu 'question'.")
    try:
        lexinfo = build_lex_query_accountant(q)
        answer, trace = answer_with_rag_accountant(q)
        debug = {"expanded_query": lexinfo.get("lex_query"), "canonical": lexinfo.get("canonical")}
        return jsonify({"answer": answer, "trace": trace, "debug": debug})
    except Exception as e:
        return _json_error(str(e), 500)

# ===================== CHAT (with FK-safe) ======================
@bp_accountant_rag.post("/chat")
@login_required
def chat_api():
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    client_sid = (data.get("session_id") or "").strip()
    if not user_text:
        return _json_error("Missing 'message'")

    user = _get_user()
    try:
        session_id = _ensure_valid_or_create_session(client_sid, user, title="Cuộc trò chuyện Accountant")
    except PermissionError as e:
        return _json_error(str(e), 403)

    add_accountant_message(session_id, "user", user_text)

    t0 = time.time()
    try:
        answer, _trace = answer_with_rag_accountant(user_text)
        add_accountant_message(session_id, "assistant", answer)
        t1 = time.time()
        return jsonify({
            "ok": True,
            "answer": answer,
            "session_id": session_id,
            "timing": {"total": round(t1 - t0, 2)}
        })
    except Exception as e:
        return _json_error(str(e), 500)

@bp_accountant_rag.post("/chat/stream")
@login_required
def chat_stream():
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    client_sid = (data.get("session_id") or "").strip()
    if not user_text:
        return _json_error("Missing 'message'")

    user = _get_user()
    try:
        session_id = _ensure_valid_or_create_session(client_sid, user, title="Cuộc trò chuyện Accountant")
    except PermissionError as e:
        return _json_error(str(e), 403)

    add_accountant_message(session_id, "user", user_text)

    def gen():
        yield f"event: ready\ndata: {json.dumps({'session_id': session_id})}\n\n"
        try:
            ans, _ = answer_with_rag_accountant(user_text)
            add_accountant_message(session_id, "assistant", ans)
            yield f"data: {json.dumps({'delta': ans})}\n\n"
            yield "event: done\ndata: {{}}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ======================= HISTORY (guarded) =======================
@bp_accountant_history.post("/new_session")
@login_required
def new_session():
    title = (request.get_json(silent=True) or {}).get("title") or "Cuộc trò chuyện Accountant"
    sid = create_accountant_session(user=_get_user(), title=title)
    return jsonify({"session_id": sid, "title": title}), 201

@bp_accountant_history.get("/sessions")
@login_required
def list_sessions():
    limit = request.args.get("limit", default=200, type=int)
    return jsonify({"sessions": get_accountant_sessions_list(user=_get_user(), limit=limit)})

@bp_accountant_history.get("/by_session")
@login_required
def get_session():
    sid = request.args.get("session_id", "").strip()
    if not sid:
        return _json_error("Missing session_id")
    owner = _get_session_owner(sid)
    if owner is None:
        return _json_error("Not found", 404)
    if owner != _get_user():
        return _json_error("Forbidden", 403)
    return jsonify({"session_id": sid, "items": get_accountant_session_messages(sid)})

@bp_accountant_history.post("/rename_session")
@login_required
def rename_session_ep():
    d = request.get_json(silent=True) or {}
    sid = d.get("session_id", "").strip()
    title = d.get("title", "").strip()
    if not sid or not title:
        return _json_error("Missing session_id or title")
    owner = _get_session_owner(sid)
    if owner is None:
        return _json_error("Not found", 404)
    if owner != _get_user():
        return _json_error("Forbidden", 403)
    rename_accountant_session(sid, title)
    return jsonify({"ok": True})

@bp_accountant_history.post("/delete_session")
@login_required
def delete_session_ep():
    d = request.get_json(silent=True) or {}
    sid = d.get("session_id", "").strip()
    if not sid:
        return _json_error("Missing session_id")
    owner = _get_session_owner(sid)
    if owner is None:
        return _json_error("Not found", 404)
    if owner != _get_user():
        return _json_error("Forbidden", 403)
    delete_accountant_session(sid)
    return jsonify({"ok": True})

@bp_accountant_history.get("/current_session")
@login_required
def current_session():
    data = get_latest_accountant_session(user=_get_user())
    if not data:
        return jsonify({"session_id": None, "items": []})
    return jsonify(data)
