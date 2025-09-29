from __future__ import annotations
import os, time, json, threading
from uuid import uuid4
from typing import Dict, Any, Optional

from flask import Blueprint, request, jsonify, session, Response, stream_with_context

# --- Auth ---
try:
    from app.Login.login_required import login_required  # type: ignore
except Exception:
    def login_required(fn):
        return fn

# --- infra: rate limit + history ---
from app.Helpers.rate_limit import get_text_limiter
from app.services.history import add_message, create_new_session

# --- HR RAG modules ---
from app.rag_hr.engine_hr import build_lex_query, answer_with_rag
from app.rag_hr.faiss_store_hr import load_faiss_vs
from app.rag_hr.hybrid_hr import hybrid_retrieve
from app.rag_hr.rerank_hr import rerank
from app.rag_hr.context_hr import build_context
from app.rag_hr.prompts_hr import get_system_prompt
from app.rag_hr.gemini_client_hr import init_gemini
from app.rag_hr.postprocess import strip_citations
from app.rag_hr.config_hr import (
    TOP_K, K_SEM, K_LEX, MAX_CHARS_CTX, W_SEM, W_LEX,
    GEMINI_MODEL_ANSWER
)

bp_hr_rag = Blueprint("hr_rag", __name__, url_prefix="/api/hr")

# ====== Semaphore cho LLM ======
LLM_SEM = threading.Semaphore(int(os.environ.get("SEM_LLM", "24")))

# ====== Helpers ======
MAX_QUESTION_LEN = 8000
def _trim(s: str, n: int = MAX_QUESTION_LEN) -> str:
    s = (s or "").strip()
    return (s[:n] + "…") if len(s) > n else s

def _json_error(msg: str, code: int = 400, **extra):
    payload = {"error": msg}
    if extra: payload.update(extra)
    return jsonify(payload), code

def _estimate_from_prompt(prompt_text: str, max_out_tokens=1024):
    words = len((prompt_text or "").split())
    return int(1.3 * words) + int(max_out_tokens or 512)

# ====== API: non-stream chat ======
@bp_hr_rag.post("/chat")
@login_required
def hr_chat():
    data = request.get_json(force=True) or {}
    user_text  = _trim(str(data.get("message", "")))
    session_id = (data.get("session_id") or "").strip()
    if not user_text:
        return _json_error("Missing message")

    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="HR RAG")
            session_id = info.get("session_id") or ""
        except Exception:
            session_id = session_id or str(uuid4())

    add_message("user", user_text, session_id=session_id)
    t0 = time.time()

    # dùng engine_hr (đã strip citation trong engine)
    try:
        lexinfo = build_lex_query(user_text)
        answer, trace = answer_with_rag(user_text)
    except Exception as e:
        return _json_error(f"Lỗi RAG: {e}", 500)

    add_message("assistant", answer, session_id=session_id)
    total = time.time() - t0

    return jsonify({
        "ok": True,
        "answer": answer,             # đã sạch citation
        "trace": trace,               # trace giữ nguyên cho debug nếu cần
        "session_id": session_id,
        "debug": {"expanded_query": lexinfo.get("lex_query"), "canonical": lexinfo.get("canonical")},
        "timing": {"total": round(total, 3)}
    })

# alias /ask
@bp_hr_rag.post("/ask")
@login_required
def ask_alias():
    data = request.get_json(silent=True) or {}
    data["message"] = data.get("question", "")
    return hr_chat()

# ====== API: stream SSE ======
@bp_hr_rag.post("/chat/stream")
@login_required
def hr_chat_stream():
    data = request.get_json(force=True) or {}
    user_text  = _trim(str(data.get("message", "")))
    session_id = (data.get("session_id") or "").strip()
    if not user_text:
        return _json_error("Missing message")

    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="HR RAG")
            session_id = info.get("session_id") or ""
        except Exception:
            session_id = session_id or str(uuid4())

    add_message("user", user_text, session_id=session_id)

    # Chuẩn bị RAG trước (không stream phần retrieve)
    vs = load_faiss_vs()
    lexinfo = build_lex_query(user_text, vs=vs)
    lex_q = lexinfo.get("lex_query") or user_text

    docs = hybrid_retrieve(vs, user_text, k_sem=K_SEM, k_lex=K_LEX, top_k=TOP_K, lex_query=lex_q, w_sem=W_SEM, w_lex=W_LEX)
    ranked = rerank(user_text, docs, top_k=TOP_K)
    ctx = build_context(ranked, max_chars=MAX_CHARS_CTX)

    genai = init_gemini()
    model = genai.GenerativeModel(GEMINI_MODEL_ANSWER, system_instruction=get_system_prompt(False))
    user_prompt = (
        "Câu hỏi: " + user_text + "\n\n"
        "Ngữ cảnh (mỗi đoạn kèm thẻ [source|chunk_id]):\n" + ctx + "\n\n"
        "Yêu cầu:\n"
        "1) Trả lời bằng tiếng Việt.\n"
        "2) Chỉ dùng thông tin từ NGỮ CẢNH. Không bịa.\n"
        "3) Khi dẫn chứng, gắn thẻ [source|chunk_id] ngay sau câu/ý tương ứng.\n"
    )

    limiter = get_text_limiter()
    est_tokens = _estimate_from_prompt(user_prompt, max_out_tokens=1024)

    def gen():
        yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'expanded_query': lex_q, 'canonical': lexinfo.get('canonical')})}\n\n"
        try:
            limiter.acquire(est_tokens)
            with LLM_SEM:
                resp = model.generate_content(user_prompt, stream=True)
                buffer = ""
                sent_len = 0
                for ev in resp:
                    chunk = getattr(ev, "text", "") or ""
                    if chunk:
                        buffer += chunk
                        sanitized = strip_citations(buffer)
                        delta = sanitized[sent_len:]
                        if delta:
                            sent_len = len(sanitized)
                            yield f"data: {json.dumps({'delta': delta})}\n\n"
                    else:
                        yield ": ping\n\n"
            limiter.on_success()
            full_answer = strip_citations(buffer)
            add_message("assistant", full_answer, session_id=session_id)
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            limiter.on_429()
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

# ====== API kiểu hộp thư (giữ tương thích) ======
_INBOX: Dict[str, Dict[str, Any]] = {}
_PROCESSED: Dict[str, Dict[str, Any]] = {}

@bp_hr_rag.post("/receive")
@login_required
def receive_message():
    data = request.get_json(silent=True) or {}
    question = _trim(str(data.get("question", "")))
    user_id: Optional[str] = (data.get("user_id") or None)
    channel: Optional[str] = (data.get("channel") or None)
    metadata: Dict[str, Any] = data.get("metadata") or {}

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

        q = (record.get("question") or "").strip()
        if not q and not direct_question:
            return _json_error("Câu hỏi trống. Gửi question ở /receive hoặc đính kèm 'question' ở đây.")
        if not q: q = direct_question

        # tái dùng chat non-stream (đã strip citation)
        with bp_hr_rag.test_request_context(json={"message": q, "session_id": str(uuid4())}):
            resp = hr_chat().json
        record["status"] = "answered"
        _PROCESSED[msg_id] = {**record, "question": q, "answer": resp.get("answer"), "trace": resp.get("trace"), "debug": resp.get("debug")}
        _INBOX.pop(msg_id, None)
        return jsonify({"message_id": msg_id, "question": q, **resp})

    if not direct_question:
        return _json_error("Thiếu 'message_id' hoặc 'question'.")
    with bp_hr_rag.test_request_context(json={"message": direct_question, "session_id": str(uuid4())}):
        return hr_chat()
