from __future__ import annotations
from flask import Blueprint, request, jsonify
from uuid import uuid4
from typing import Dict, Any, Optional

# (Tuỳ chọn) Auth
try:
    from app.Login.login_required import login_required  # type: ignore
except Exception:
    def login_required(fn):  # no-op nếu không có middleware
        return fn

from src.app.rag_hr.engine_hr import answer_with_rag

bp_hr_rag = Blueprint("hr_rag", __name__, url_prefix="/api/hr")

_INBOX: Dict[str, Dict[str, Any]] = {}
_PROCESSED: Dict[str, Dict[str, Any]] = {}

MAX_QUESTION_LEN = 8000

def _trim(s: str, n: int = MAX_QUESTION_LEN) -> str:
    s = (s or "").strip()
    return (s[:n] + "…") if len(s) > n else s

def _json_error(msg: str, code: int = 400, **extra):
    payload = {"error": msg}
    if extra:
        payload.update(extra)
    return jsonify(payload), code

@bp_hr_rag.post("/receive")
@login_required
def receive_message():
    data = request.get_json(silent=True) or {}
    question = _trim(str(data.get("question", "")))
    user_id: Optional[str] = (data.get("user_id") or None)
    channel: Optional[str] = (data.get("channel") or None)
    metadata: Dict[str, Any] = data.get("metadata") or {}

    msg_id = str(uuid4())
    _INBOX[msg_id] = {
        "question": question,
        "user_id": user_id,
        "channel": channel,
        "metadata": metadata,
        "status": "received",
    }
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
                })
            return _json_error(f"message_id '{msg_id}' không tồn tại", 404)

        q = (record.get("question") or "").strip()
        if not q and not direct_question:
            return _json_error("Câu hỏi trống. Gửi question ở /receive hoặc đính kèm 'question' ở đây.")

        if not q:
            q = direct_question

        try:
            answer, trace = answer_with_rag(q)
            record["status"] = "answered"
            _PROCESSED[msg_id] = {**record, "question": q, "answer": answer, "trace": trace}
            _INBOX.pop(msg_id, None)
            return jsonify({"message_id": msg_id, "question": q, "answer": answer, "trace": trace})
        except Exception as e:
            record["status"] = "error"
            return _json_error(str(e), 500, message_id=msg_id)

    if not direct_question:
        return _json_error("Thiếu 'message_id' hoặc 'question'.")

    try:
        answer, trace = answer_with_rag(direct_question)
        return jsonify({"question": direct_question, "answer": answer, "trace": trace})
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
        answer, trace = answer_with_rag(q)
        return jsonify({"answer": answer, "trace": trace})
    except Exception as e:
        return _json_error(str(e), 500)