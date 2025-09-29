from __future__ import annotations
import os, json, time
from flask import Blueprint, request, jsonify, Response, stream_with_context, session
from uuid import uuid4
from typing import Dict, Any, Optional

# login_required (fallback no-op nếu không có)
try:
    from app.Login.login_required import login_required  # type: ignore
except Exception:
    def login_required(fn): return fn

# optional history service (fallback no-op)
try:
    from app.services.history import get_history, add_message, create_new_session
except Exception:
    def get_history(): return []
    def add_message(role, content, session_id=None): pass
    def create_new_session(user="", title="Cuộc trò chuyện mới"): return {"session_id": str(uuid4())}

from app.rag_hr.engine_hr import answer_with_rag, build_lex_query

bp_hr_rag = Blueprint("hr_rag", __name__, url_prefix="/api/hr")

_INBOX: Dict[str, Dict[str, Any]] = {}
_PROCESSED: Dict[str, Dict[str, Any]] = {}
MAX_QUESTION_LEN = 8000

def _trim(s: str, n: int = MAX_QUESTION_LEN) -> str:
    s = (s or "").strip()
    return (s[:n] + "…") if len(s) > n else s

def _json_error(msg: str, code: int = 400, **extra):
    payload = {"error": msg}
    if extra: payload.update(extra)
    return jsonify(payload), code

# ========== Receive / Reply / Ask ==========
@bp_hr_rag.post("/receive")
@login_required
def receive_message():
    data = request.get_json(silent=True) or {}
    question = _trim(str(data.get("question", "")))
    user_id: Optional[str] = (data.get("user_id") or None)
    channel: Optional[str] = (data.get("channel") or None)
    metadata: Dict[str, Any] = data.get("metadata") or {}

    if not question:
        return _json_error("Thiếu 'question'.")

    msg_id = str(uuid4())
    _INBOX[msg_id] = {"question": question, "user_id": user_id, "channel": channel, "metadata": metadata, "status": "received"}
    return jsonify({"message_id": msg_id, "status": "received"}), 201

@bp_hr_rag.post("/reply")
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
                    "debug": processed.get("debug")
                })
            return _json_error(f"message_id '{msg_id}' không tồn tại", 404)

        q = (record.get("question") or "").strip() or direct_question
        if not q:
            return _json_error("Câu hỏi trống.")

        try:
            lexinfo = build_lex_query(q)  # debug client
            answer, trace = answer_with_rag(q)
            record["status"] = "answered"
            debug = {"expanded_query": lexinfo.get("lex_query"), "canonical": lexinfo.get("canonical")}
            _PROCESSED[msg_id] = {**record, "question": q, "answer": answer, "trace": trace, "debug": debug}
            _INBOX.pop(msg_id, None)
            return jsonify({"message_id": msg_id, "question": q, "answer": answer, "trace": trace, "debug": debug})
        except Exception as e:
            record["status"] = "error"
            return _json_error(str(e), 500, message_id=msg_id)

    if not direct_question:
        return _json_error("Thiếu 'message_id' hoặc 'question'.")
    try:
        lexinfo = build_lex_query(direct_question)
        answer, trace = answer_with_rag(direct_question)
        debug = {"expanded_query": lexinfo.get("lex_query"), "canonical": lexinfo.get("canonical")}
        return jsonify({"question": direct_question, "answer": answer, "trace": trace, "debug": debug})
    except Exception as e:
        return _json_error(str(e), 500)

@bp_hr_rag.post("/ask")
@login_required
def ask_direct():
    data = request.get_json(silent=True) or {}
    q = _trim(str(data.get("question", "")))
    if not q:
        return _json_error("Thiếu 'question'.")
    try:
        lexinfo = build_lex_query(q)
        answer, trace = answer_with_rag(q)
        debug = {"expanded_query": lexinfo.get("lex_query"), "canonical": lexinfo.get("canonical")}
        return jsonify({"answer": answer, "trace": trace, "debug": debug})
    except Exception as e:
        return _json_error(str(e), 500)

# ========== Chat API (UI dùng) ==========
@bp_hr_rag.post("/chat")
@login_required
def chat_api():
    data = request.get_json(force=True) or {}
    user_text  = (data.get('message') or "").strip()
    session_id = (data.get('session_id') or "").strip()
    if not user_text:
        return _json_error("Missing 'message'")

    # nếu không có session_id -> tạo
    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện HR")
            session_id = info.get("session_id") or ""
        except Exception:
            session_id = ""

    add_message("user", user_text, session_id=session_id)

    t0 = time.time()
    try:
        answer, _trace = answer_with_rag(user_text)
        add_message("assistant", answer, session_id=session_id)
        t1 = time.time()
        return jsonify({
            "ok": True,
            "answer": answer,
            "session_id": session_id,
            "timing": {"total": round(t1 - t0, 2)}
        })
    except Exception as e:
        return _json_error(str(e), 500)

# Stream (dùng SSE). Ở đây stream theo block sau khi xử lý (không phải token-by-token)
@bp_hr_rag.post("/chat/stream")
@login_required
def chat_stream():
    data = request.get_json(force=True) or {}
    user_text  = (data.get('message') or "").strip()
    session_id = (data.get('session_id') or "").strip()
    if not user_text:
        return _json_error("Missing 'message'")

    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện HR")
            session_id = info.get("session_id") or ""
        except Exception:
            session_id = ""

    add_message("user", user_text, session_id=session_id)

    def gen():
        yield f"event: ready\ndata: {json.dumps({'session_id': session_id})}\n\n"
        try:
            ans, _ = answer_with_rag(user_text)
            add_message("assistant", ans, session_id=session_id)
            # đẩy một phát full (nếu muốn từng khúc, bạn có thể chunk theo đoạn xuống dòng)
            yield f"data: {json.dumps({'delta': ans})}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return Response(stream_with_context(gen()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
