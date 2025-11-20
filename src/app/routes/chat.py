from __future__ import annotations
import time, json, re, os
from flask import Blueprint, request, jsonify, session, Response, stream_with_context
from app.Helpers.rate_limit import get_text_limiter
from app.services.history import get_history, add_message, create_new_session
from app.Helpers.prompt_internal import SYSTEM_PRIMER
from app.Model_LLM.model_llm import LLM_model
# from app.Helpers.prompt_KT import persona_vi
from app.Model_LLM.hybrid_retriever import rerank, TOP_K
from app.config.settings import ChatConfig
from app.Login.login_required import build_principal_from_session
from app.Model_LLM.Chat_Database.db_router import handle_db_message
from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx

bp = Blueprint('chat', __name__)

# ====== LLM helpers kept local to this module ======
LLM_SEM = ChatConfig.LLM_SEM
DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.65"))
REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {"0", "false", "False"}


def _estimate_from_contents(contents, max_out_tokens=1024):
    words = 0
    for m in contents or []:
        for p in (m.get("parts") or []):
            if isinstance(p, dict) and p.get("text"):
                words += len(p["text"].split())
    return int(1.3 * words) + int(max_out_tokens or 512)


def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
    limiter = get_text_limiter()
    max_out = config.get("max_output_tokens") if isinstance(config, dict) else getattr(config, "max_output_tokens", 1024)
    tokens_est = _estimate_from_contents(contents, max_out)
    last_err = None
    for i in range(retries + 1):
        try:
            limiter.acquire(tokens_est)
            t0 = time.time()
            with LLM_SEM:
                resp = gclient.models.generate_content(model=model, contents=contents, config=config)
            limiter.on_success()
            return (getattr(resp, "text", "") or ""), time.time() - t0
        except Exception as e:
            last_err = e
            s = str(e).lower()
            if ("429" in s or "quota" in s or "rate" in s) and i < retries:
                limiter.on_429()
                time.sleep(backoff * (2 ** i))
                continue
            limiter.on_429()
            raise last_err


_SOURCE_TAG_PAT = re.compile(
    r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
    re.IGNORECASE,
)


def strip_source_citations(text: str) -> str:
    if not text:
        return text
    text = _SOURCE_TAG_PAT.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def _to_gemini_history_no_system(history_msgs):
    out = []
    for m in history_msgs:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = "model" if role == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": content}]})
    return out


def _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, answer_text: str) -> str:
    """
    Làm mềm câu chữ, nhưng KHÔNG thay đổi số liệu, mã đơn, phần trăm.
    """
    if not REWRITE_DB_WITH_LLM:
        return answer_text
    guard =   SYSTEM_PRIMER + "YÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô.\n Không thêm bớt số. Nếu một số không cần thiết có quyền bỏ. Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}"
                }
            ],
        }
    ]
    try:
        out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        out = strip_source_citations(out or "")
        # sanity: nếu bản mới mất hết số mà bản cũ có → giữ bản cũ
        has_num_old = re.search(r"\d", answer_text or "") is not None
        has_num_new = re.search(r"\d", out or "") is not None
        if has_num_old and not has_num_new:
            return answer_text
        return out or answer_text
    except Exception:
        return answer_text


# =========================
# Core RAG
# =========================
def _rag_answer(user_text: str, gclient, GEMINI_MODEL, GEN_CFG, embeddings, retriever):
    # 1) embed (best-effort)
    try:
        t0 = time.time()
        _ = embeddings.embed_query("query: " + user_text)
        embed_time = time.time() - t0
    except Exception:
        embed_time = 0.0

    # 2) retrieve + rerank
    docs_text, search_time = "", 0.0
    try:
        t0 = time.time()
        candidates = retriever.get_relevant_documents("query: " + user_text)
        ranked = rerank(user_text, candidates, top_k=TOP_K)
        parts, total = [], 0
        for d, _score in ranked:
            txt = d.page_content
            if txt.lower().startswith("passage: "):
                txt = txt[len("passage: ") :]
            parts.append(txt)
            total += len(txt)
            if total > 4000:
                break
        docs_text = "\n\n---\n\n".join(parts) if parts else ""
        search_time = time.time() - t0
    except Exception:
        pass

    context_hint = (
        f"Context (trích từ tài liệu):\n{docs_text}"
        if docs_text
        else "(Không tìm thấy dữ liệu context phù hợp.)"
    )
    system_prompt = f"""{SYSTEM_PRIMER}
{context_hint}
"""
    hist_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in get_history()
        if m["role"] in ("user", "assistant")
    ]
    contents = _to_gemini_history_no_system(hist_msgs)
    first_user_text = f"""[SYSTEM]
{system_prompt}

[USER]
{user_text}"""
    contents.append({"role": "user", "parts": [{"text": first_user_text}]})
    try:
        result, llm_time = _safe_gemini_generate(
            gclient, GEMINI_MODEL, contents, GEN_CFG
        )
    except Exception as e:
        result, llm_time = (f"Lỗi khi gọi Gemini API: {e}", 0.0)
    result = strip_source_citations(result)
    return result, {
        "embedding": round(embed_time, 2),
        "search": round(search_time, 2),
        "llm": round(llm_time, 2),
    }


# =========================
# HTTP endpoints
# =========================
@bp.route("/api/chat", methods=["POST"])
def chat_api():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    # principal thực từ session đăng nhập
    principal = build_principal_from_session()

    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    # Server cấp session nếu client chưa có
    if not session_id:
        try:
            info = create_new_session(
                session.get("user") or "", title="Cuộc trò chuyện mới"
            )
            session_id = info.get("session_id") or ""
        except Exception:
            pass

    # Lưu user message
    add_message("user", user_text, session_id=session_id)
    full_start = time.time()

    # ===== 1) Thử nhánh DB trước (intent-based) =====
    handled, db_answer, meta = handle_db_message(
        user_text, session_id, principal=principal
    )
    branch = "db" if handled else "rag"
    timing = {"embedding": 0.0, "search": 0.0, "llm": 0.0}

    if handled:
        final_answer = _rewrite_db_answer(
            gclient, GEMINI_MODEL, GEN_CFG, db_answer
        )
        # lưu context router vào Redis (nếu Redis up, redis_ctx đã tự handle lỗi)
        try:
            if isinstance(meta, dict):
                update_ctx(
                    session_id,
                    {
                        "last_branch": "db",
                        "last_intent": meta.get("intent"),
                        "time_window": meta.get("time_window"),
                    },
                )
            else:
                update_ctx(session_id, {"last_branch": "db"})
        except Exception:
            pass
    else:
        # ===== 2) RAG =====
        final_answer, timing = _rag_answer(
            user_text, gclient, GEMINI_MODEL, GEN_CFG, embeddings, retriever
        )
        try:
            update_ctx(session_id, {"last_branch": "rag"})
        except Exception:
            pass

    # Lưu assistant message
    add_message("assistant", final_answer, session_id=session_id)

    elapsed = time.time() - full_start
    return jsonify(
        {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": branch,
            "meta": meta,
            "timing": {
                "total": round(elapsed, 2),
                **timing,
            },
        }
    )


@bp.route("/chat", methods=["POST"])
def chat_api_alias():
    return chat_api()


@bp.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    # principal thực từ session (không tin client gửi lên)
    principal = build_principal_from_session()

    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    if not session_id:
        try:
            info = create_new_session(
                session.get("user") or "", title="Cuộc trò chuyện mới"
            )
            session_id = info.get("session_id") or ""
        except Exception:
            pass

    # Lưu user message trước khi stream
    add_message("user", user_text, session_id=session_id)

    # Kiểm tra intent DB ngay ở đầu: nếu là DB thì trả **không stream**
    handled, db_answer, meta = handle_db_message(
        user_text, session_id, principal=principal
    )
    if handled:
        final_answer = _rewrite_db_answer(
            gclient, GEMINI_MODEL, GEN_CFG, db_answer
        )
        add_message("assistant", final_answer, session_id=session_id)

        try:
            if isinstance(meta, dict):
                update_ctx(
                    session_id,
                    {
                        "last_branch": "db",
                        "last_intent": meta.get("intent"),
                        "time_window": meta.get("time_window"),
                    },
                )
            else:
                update_ctx(session_id, {"last_branch": "db"})
        except Exception:
            pass

        return jsonify(
            {
                "ok": True,
                "answer": final_answer,
                "session_id": session_id,
                "branch": "db",
                "meta": meta,
            }
        )

    # Nếu không phải DB → stream RAG
    hist_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in get_history()
        if m["role"] in ("user", "assistant")
    ]
    contents = _to_gemini_history_no_system(hist_msgs)
    context_hint = "(Stream mode - context omitted)"
    system_prompt = f"""{SYSTEM_PRIMER}
{context_hint}
"""
    first_user_text = f"""[SYSTEM]
{system_prompt}

[USER]
{user_text}"""
    contents.append({"role": "user", "parts": [{"text": first_user_text}]})

    limiter = get_text_limiter()
    tokens_est = _estimate_from_contents(
        contents, GEN_CFG.get("max_output_tokens", 1024)
    )

    def gen():
        # Thông báo ready cho client
        yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'branch': 'rag'})}\n\n"
        try:
            limiter.acquire(tokens_est)
            with LLM_SEM:
                resp = gclient.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=GEN_CFG,
                    stream=True,
                )
                acc = []
                for ev in resp:
                    chunk = getattr(ev, "text", "") or ""
                    if chunk:
                        acc.append(chunk)
                        yield f"data: {json.dumps({'delta': chunk})}\n\n"
                    else:
                        # keep-alive
                        yield ": keep-alive\n\n"
            limiter.on_success()
            full_answer = strip_source_citations("".join(acc).strip())
            add_message("assistant", full_answer, session_id=session_id)

            try:
                update_ctx(session_id, {"last_branch": "rag"})
            except Exception:
                pass

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            limiter.on_429()
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# # app/routes/chat.py
# # -*- coding: utf-8 -*-
# from __future__ import annotations
# import time, json, re, os
# from flask import Blueprint, request, jsonify, session, Response, stream_with_context
# from werkzeug.security import check_password_hash
# from ..Login.login_required import get_user
# from app.Helpers.rate_limit import get_text_limiter
# from app.services.history import get_history, add_message, create_new_session
# from app.Helpers.prompt_internal import SYSTEM_PRIMER
# from app.Model_LLM.model_llm import LLM_model
# from app.Helpers.prompt_KT import persona_vi
# from app.Model_LLM.hybrid_retriever import rerank, TOP_K
# from app.config.settings import ChatConfig
# from app.Login.login_required import build_principal_from_session
# from app.Model_LLM.Chat_Database.db_router import handle_db_message
# from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx

# bp = Blueprint('chat', __name__)

# # ====== LLM helpers kept local to this module ======
# LLM_SEM = ChatConfig.LLM_SEM
# DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.65"))
# REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {"0","false","False"}

# def _estimate_from_contents(contents, max_out_tokens=1024):
#     words = 0
#     for m in contents or []:
#         for p in (m.get("parts") or []):
#             if isinstance(p, dict) and p.get("text"):
#                 words += len(p["text"].split())
#     return int(1.3 * words) + int(max_out_tokens or 512)

# def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
#     limiter = get_text_limiter()
#     max_out = config.get("max_output_tokens") if isinstance(config, dict) else getattr(config, "max_output_tokens", 1024)
#     tokens_est = _estimate_from_contents(contents, max_out)
#     last_err = None
#     for i in range(retries + 1):
#         try:
#             limiter.acquire(tokens_est)
#             t0 = time.time()
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(model=model, contents=contents, config=config)
#             limiter.on_success()
#             return (getattr(resp, "text", "") or ""), time.time() - t0
#         except Exception as e:
#             last_err = e
#             s = str(e).lower()
#             if ("429" in s or "quota" in s or "rate" in s) and i < retries:
#                 limiter.on_429(); time.sleep(backoff * (2 ** i)); continue
#             limiter.on_429(); raise last_err

# _SOURCE_TAG_PAT = re.compile(r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]", re.IGNORECASE)

# def strip_source_citations(text: str) -> str:
#     if not text: return text
#     text = _SOURCE_TAG_PAT.sub("", text)
#     text = re.sub(r"[ \t]{2,}", " ", text)
#     text = re.sub(r"\s+([,.;:!?])", r"\1", text)
#     return text.strip()

# def _to_gemini_history_no_system(history_msgs):
#     out = []
#     for m in history_msgs:
#         role = m.get("role", "user")
#         content = (m.get("content") or "").strip()
#         if not content: continue
#         role = "model" if role == "assistant" else "user"
#         out.append({"role": role, "parts": [{"text": content}]})
#     return out

# def _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, answer_text: str) -> str:
#     """
#     Làm mềm câu chữ, nhưng KHÔNG thay đổi số liệu, mã đơn, phần trăm.
#     """
#     if not REWRITE_DB_WITH_LLM: return answer_text
#     guard = (
#         "Bạn là biên tập viên. YÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô. "
#         "Không thêm bớt số. Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
#     )
#     contents = [
#         {"role":"user","parts":[{"text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}"}]}
#     ]
#     try:
#         out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#         out = strip_source_citations(out or "")
#         # sanity: nếu không thấy số nào trong bản mới mà bản cũ có → dùng bản cũ
#         has_num_old = re.search(r"\d", answer_text or "") is not None
#         has_num_new = re.search(r"\d", out or "") is not None
#         if has_num_old and not has_num_new:
#             return answer_text
#         return out or answer_text
#     except Exception:
#         return answer_text

# # =========================
# # Core routing
# # =========================
# def _rag_answer(user_text: str, gclient, GEMINI_MODEL, GEN_CFG, embeddings, retriever):
#     # 1) embed (best-effort)
#     try:
#         t0 = time.time(); _ = embeddings.embed_query("query: " + user_text); embed_time = time.time() - t0
#     except Exception: embed_time = 0.0

#     # 2) retrieve + rerank
#     docs_text, search_time = "", 0.0
#     try:
#         t0 = time.time()
#         candidates = retriever.get_relevant_documents("query: " + user_text)
#         ranked = rerank(user_text, candidates, top_k=TOP_K)
#         parts, total = [], 0
#         for d, _score in ranked:
#             txt = d.page_content
#             if txt.lower().startswith("passage: "): txt = txt[len("passage: "):]
#             parts.append(txt); total += len(txt)
#             if total > 4000: break
#         docs_text = "\n\n---\n\n".join(parts) if parts else ""
#         search_time = time.time() - t0
#     except Exception:
#         pass

#     context_hint = f"Context (trích từ tài liệu):\n{docs_text}" if docs_text else "(Không tìm thấy dữ liệu context phù hợp.)"
#     system_prompt = f"""{SYSTEM_PRIMER}
# {context_hint}
# """
#     hist_msgs = [{"role": m["role"], "content": m["content"]} for m in get_history() if m["role"] in ("user", "assistant")]
#     contents = _to_gemini_history_no_system(hist_msgs)
#     first_user_text = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user_text}]})
#     try:
#         result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     except Exception as e:
#         result, llm_time = (f"Lỗi khi gọi Gemini API: {e}", 0.0)
#     result = strip_source_citations(result)
#     return result, {"embedding": round(embed_time,2), "search": round(search_time,2), "llm": round(llm_time,2)}

# # =========================
# # HTTP endpoints
# # =========================
# @bp.route('/api/chat', methods=['POST'])
# def chat_api():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
#     data = request.get_json(force=True) or {}
#     user_text  = (data.get('message') or "").strip()
#     session_id = (data.get('session_id') or "").strip()
#     principal = build_principal_from_session()

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     # Server cấp session nếu client chưa có
#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or ""
#         except Exception:
#             pass

#     # Lưu user message
#     add_message("user", user_text, session_id=session_id)
#     full_start = time.time()

#     # ===== 1) Thử nhánh DB trước (intent-based) =====
#     handled, db_answer, meta = handle_db_message(user_text, session_id, principal=principal)
#     branch = "db" if handled else "rag"
#     timing = {"embedding": 0.0, "search": 0.0, "llm": 0.0}

#     if handled:
#         # chỉ “làm mềm” nếu bật cờ
#         final_answer = _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, db_answer)
#     else:
#         # ===== 2) RAG =====
#         final_answer, timing = _rag_answer(user_text, gclient, GEMINI_MODEL, GEN_CFG, embeddings, retriever)

#     # Lưu assistant message
#     add_message("assistant", final_answer, session_id=session_id)

#     elapsed = time.time() - full_start
#     return jsonify({
#         "ok": True,
#         "answer": final_answer,
#         "session_id": session_id,
#         "branch": branch,
#         "meta": meta,
#         "timing": {
#             "total": round(elapsed, 2),
#             **timing
#         }
#     })


# @bp.route('/chat', methods=['POST'])
# def chat_api_alias():
#     return chat_api()

# @bp.route('/api/chat/stream', methods=['POST'])
# def chat_stream():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
#     data = request.get_json(force=True) or {}
#     user_text  = (data.get('message') or "").strip()
#     session_id = (data.get('session_id') or "").strip()

#     # NEW: principal cho stream
#     principal = data.get("principal") or {}

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or ""
#         except Exception:
#             pass

#     # Lưu user message trước khi stream
#     add_message("user", user_text, session_id=session_id)

#     # Kiểm tra intent DB ngay ở đầu: nếu là DB thì trả **không stream** (vì DB là kết quả tức thời)
#     handled, db_answer, meta = handle_db_message(user_text, session_id, principal=principal)
#     if handled:
#         final_answer = _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, db_answer)
#         add_message("assistant", final_answer, session_id=session_id)
#         return jsonify({
#             "ok": True,
#             "answer": final_answer,
#             "session_id": session_id,
#             "branch": "db",
#             "meta": meta
#         })

#     # Nếu không phải DB → stream RAG
#     hist_msgs = [{"role": m["role"], "content": m["content"]} for m in get_history() if m["role"] in ("user", "assistant")]
#     contents = _to_gemini_history_no_system(hist_msgs)
#     context_hint = "(Stream mode - context omitted)"
#     system_prompt = f"""{SYSTEM_PRIMER}
# {context_hint}
# """
#     first_user_text = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user_text}]})

#     limiter = get_text_limiter()
#     tokens_est = _estimate_from_contents(contents, GEN_CFG.get("max_output_tokens", 1024))

#     def gen():
#         yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'branch': 'rag'})}\n\n"
#         try:
#             limiter.acquire(tokens_est)
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(model=GEMINI_MODEL, contents=contents, config=GEN_CFG, stream=True)
#                 acc = []
#                 for ev in resp:
#                     chunk = getattr(ev, "text", "") or ""
#                     if chunk:
#                         acc.append(chunk)
#                         yield f"data: {json.dumps({'delta': chunk})}\n\n"
#                     else:
#                         yield ': keep-alive\n\n'
#             limiter.on_success()
#             full_answer = strip_source_citations("".join(acc).strip())
#             add_message("assistant", full_answer, session_id=session_id)
#             yield "event: done\ndata: {}\n\n"
#         except Exception as e:
#             limiter.on_429()
#             yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

#     return Response(
#         stream_with_context(gen()),
#         mimetype="text/event-stream",
#         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
#     )



# # app/routes/chat.py
# # -*- coding: utf-8 -*-
# from __future__ import annotations
# import time, json, re, os
# from flask import Blueprint, request, jsonify, session, Response, stream_with_context

# from app.Helpers.rate_limit import get_text_limiter
# from app.services.history import get_history, add_message, create_new_session
# from app.Helpers.prompt_internal import SYSTEM_PRIMER
# from app.Model_LLM.model_llm import LLM_model
# from app.Helpers.prompt_KT import persona_vi
# from app.Model_LLM.hybrid_retriever import rerank, TOP_K
# from app.config.settings import ChatConfig

# # NEW: DB router + Redis context
# from app.Model_LLM.Chat_Database.db_router import handle_db_message
# from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx

# bp = Blueprint('chat', __name__)

# # ====== LLM helpers kept local to this module ======
# LLM_SEM = ChatConfig.LLM_SEM
# DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.7"))
# REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {"0", "false", "False"}


# def _estimate_from_contents(contents, max_out_tokens=1024):
#     words = 0
#     for m in contents or []:
#         for p in (m.get("parts") or []):
#             if isinstance(p, dict) and p.get("text"):
#                 words += len(p["text"].split())
#     return int(1.3 * words) + int(max_out_tokens or 512)


# def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
#     limiter = get_text_limiter()
#     max_out = config.get("max_output_tokens") if isinstance(config, dict) else getattr(config, "max_output_tokens", 1024)
#     tokens_est = _estimate_from_contents(contents, max_out)
#     last_err = None
#     for i in range(retries + 1):
#         try:
#             limiter.acquire(tokens_est)
#             t0 = time.time()
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(model=model, contents=contents, config=config)
#             limiter.on_success()
#             return (getattr(resp, "text", "") or ""), time.time() - t0
#         except Exception as e:
#             last_err = e
#             s = str(e).lower()
#             if ("429" in s or "quota" in s or "rate" in s) and i < retries:
#                 limiter.on_429()
#                 time.sleep(backoff * (2 ** i))
#                 continue
#             limiter.on_429()
#             raise last_err


# _SOURCE_TAG_PAT = re.compile(r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]", re.IGNORECASE)


# def strip_source_citations(text: str) -> str:
#     if not text:
#         return text
#     text = _SOURCE_TAG_PAT.sub("", text)
#     text = re.sub(r"[ \t]{2,}", " ", text)
#     text = re.sub(r"\s+([,.;:!?])", r"\1", text)
#     return text.strip()


# def _to_gemini_history_no_system(history_msgs):
#     out = []
#     for m in history_msgs:
#         role = m.get("role", "user")
#         content = (m.get("content") or "").strip()
#         if not content:
#             continue
#         role = "model" if role == "assistant" else "user"
#         out.append({"role": role, "parts": [{"text": content}]})
#     return out


# def _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, answer_text: str) -> str:
#     """
#     Làm mềm câu chữ, nhưng KHÔNG thay đổi số liệu, mã đơn, phần trăm.
#     """
#     if not REWRITE_DB_WITH_LLM:
#         return answer_text
#     guard = (
#         "Bạn là biên tập viên. YÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô. "
#         "Không thêm bớt số. Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
#     )
#     contents = [
#         {"role": "user", "parts": [{"text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}"}]}
#     ]
#     try:
#         out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#         out = strip_source_citations(out or "")
#         # sanity: nếu không thấy số nào trong bản mới mà bản cũ có → dùng bản cũ
#         has_num_old = re.search(r"\d", answer_text or "") is not None
#         has_num_new = re.search(r"\d", out or "") is not None
#         if has_num_old and not has_num_new:
#             return answer_text
#         return out or answer_text
#     except Exception:
#         return answer_text


# # =========================
# # Core routing (RAG + Redis context)
# # =========================
# def _rag_answer(user_text: str,
#                 session_id: str,
#                 gclient,
#                 GEMINI_MODEL,
#                 GEN_CFG,
#                 embeddings,
#                 retriever):
#     """
#     Trả lời theo RAG, có dùng:
#     - Vector store (retriever + rerank)
#     - Ngữ cảnh tóm tắt từ Redis theo session_id (get_ctx)
#     """
#     # 0) Lấy context tóm tắt từ Redis
#     redis_ctx_text = ""
#     try:
#         redis_ctx_text = get_ctx(session_id) or ""
#     except Exception:
#         redis_ctx_text = ""

#     # 1) embed (best-effort)
#     try:
#         t0 = time.time()
#         _ = embeddings.embed_query("query: " + user_text)
#         embed_time = time.time() - t0
#     except Exception:
#         embed_time = 0.0

#     # 2) retrieve + rerank
#     docs_text, search_time = "", 0.0
#     try:
#         t0 = time.time()
#         candidates = retriever.get_relevant_documents("query: " + user_text)
#         ranked = rerank(user_text, candidates, top_k=TOP_K)
#         parts, total = [], 0
#         for d, _score in ranked:
#             txt = d.page_content
#             if txt.lower().startswith("passage: "):
#                 txt = txt[len("passage: "):]
#             parts.append(txt)
#             total += len(txt)
#             if total > 4000:
#                 break
#         docs_text = "\n\n---\n\n".join(parts) if parts else ""
#         search_time = time.time() - t0
#     except Exception:
#         pass

#     ctx_block = (
#         f"Ngữ cảnh hội thoại trước (tóm tắt từ Redis, có thể không đầy đủ):\n{redis_ctx_text}\n\n"
#         if redis_ctx_text else
#         "Chưa có tóm tắt ngữ cảnh đáng kể từ Redis cho phiên này.\n\n"
#     )

#     knowledge_block = (
#         f"Context (trích từ tài liệu RAG):\n{docs_text}"
#         if docs_text else
#         "(Không tìm thấy dữ liệu context RAG phù hợp.)"
#     )

#     system_prompt = f"""{SYSTEM_PRIMER}

# [CONVERSATION_CONTEXT]
# {ctx_block}

# [KNOWLEDGE_CONTEXT]
# {knowledge_block}
# """

#     # Lịch sử chi tiết (DB history) – vẫn giữ nhưng Gemini đã có tóm tắt từ Redis
#     hist_msgs = [
#         {"role": m["role"], "content": m["content"]}
#         for m in get_history()
#         if m["role"] in ("user", "assistant")
#     ]
#     contents = _to_gemini_history_no_system(hist_msgs)

#     first_user_text = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user_text}]})

#     try:
#         result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     except Exception as e:
#         result, llm_time = (f"Lỗi khi gọi Gemini API: {e}", 0.0)
#     result = strip_source_citations(result)
#     return result, {"embedding": round(embed_time, 2), "search": round(search_time, 2), "llm": round(llm_time, 2)}


# # =========================
# # HTTP endpoints
# # =========================
# @bp.route('/api/chat', methods=['POST'])
# def chat_api():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
#     data = request.get_json(force=True) or {}
#     user_text = (data.get('message') or "").strip()
#     session_id = (data.get('session_id') or "").strip()
#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     # Server cấp session nếu client chưa có
#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or ""
#         except Exception:
#             pass

#     # Lưu user message
#     add_message("user", user_text, session_id=session_id)
#     # Cập nhật Redis context với câu người dùng
#     try:
#         update_ctx(session_id, "user", user_text)
#     except Exception:
#         pass

#     full_start = time.time()

#     # ===== 1) Thử nhánh DB trước (intent-based) =====
#     handled, db_answer, meta = handle_db_message(user_text, session_id)
#     branch = "db" if handled else "rag"
#     timing = {"embedding": 0.0, "search": 0.0, "llm": 0.0}

#     if handled:
#         # chỉ “làm mềm” nếu bật cờ
#         final_answer = _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, db_answer)
#     else:
#         # ===== 2) RAG (có Redis context) =====
#         final_answer, timing = _rag_answer(
#             user_text=user_text,
#             session_id=session_id,
#             gclient=gclient,
#             GEMINI_MODEL=GEMINI_MODEL,
#             GEN_CFG=GEN_CFG,
#             embeddings=embeddings,
#             retriever=retriever,
#         )

#     # Lưu assistant message
#     add_message("assistant", final_answer, session_id=session_id)
#     # Cập nhật Redis context với câu trả lời
#     try:
#         update_ctx(session_id, "assistant", final_answer)
#     except Exception:
#         pass

#     elapsed = time.time() - full_start
#     return jsonify({
#         "ok": True,
#         "answer": final_answer,
#         "session_id": session_id,
#         "branch": branch,
#         "meta": meta,
#         "timing": {
#             "total": round(elapsed, 2),
#             **timing
#         }
#     })


# @bp.route('/chat', methods=['POST'])
# def chat_api_alias():
#     return chat_api()


# @bp.route('/api/chat/stream', methods=['POST'])
# def chat_stream():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
#     data = request.get_json(force=True) or {}
#     user_text = (data.get('message') or "").strip()
#     session_id = (data.get('session_id') or "").strip()
#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or ""
#         except Exception:
#             pass

#     # Lưu user message trước khi stream
#     add_message("user", user_text, session_id=session_id)
#     # Cập nhật Redis context với câu người dùng
#     try:
#         update_ctx(session_id, "user", user_text)
#     except Exception:
#         pass

#     # Kiểm tra intent DB ngay ở đầu: nếu là DB thì trả **không stream**
#     handled, db_answer, meta = handle_db_message(user_text, session_id)
#     if handled:
#         final_answer = _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, db_answer)
#         add_message("assistant", final_answer, session_id=session_id)
#         # Cập nhật Redis context với câu trả lời từ DB
#         try:
#             update_ctx(session_id, "assistant", final_answer)
#         except Exception:
#             pass
#         return jsonify({
#             "ok": True,
#             "answer": final_answer,
#             "session_id": session_id,
#             "branch": "db",
#             "meta": meta
#         })

#     # Nếu không phải DB → stream RAG
#     hist_msgs = [
#         {"role": m["role"], "content": m["content"]}
#         for m in get_history()
#         if m["role"] in ("user", "assistant")
#     ]
#     contents = _to_gemini_history_no_system(hist_msgs)

#     # Lấy tóm tắt từ Redis cho stream
#     redis_ctx_text = ""
#     try:
#         redis_ctx_text = get_ctx(session_id) or ""
#     except Exception:
#         redis_ctx_text = ""

#     ctx_block = (
#         f"Ngữ cảnh hội thoại trước (tóm tắt từ Redis, mode stream):\n{redis_ctx_text}\n\n"
#         if redis_ctx_text else
#         "Chưa có tóm tắt ngữ cảnh đáng kể từ Redis cho phiên này.\n\n"
#     )

#     context_hint = "(Stream mode - context RAG chi tiết được lược bớt để giảm độ trễ.)"
#     system_prompt = f"""{SYSTEM_PRIMER}

# [CONVERSATION_CONTEXT]
# {ctx_block}

# [NOTES]
# {context_hint}
# """

#     first_user_text = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user_text}]})

#     limiter = get_text_limiter()
#     tokens_est = _estimate_from_contents(contents, GEN_CFG.get("max_output_tokens", 1024))

#     def gen():
#         yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'branch': 'rag'})}\n\n"
#         try:
#             limiter.acquire(tokens_est)
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(
#                     model=GEMINI_MODEL,
#                     contents=contents,
#                     config=GEN_CFG,
#                     stream=True
#                 )
#                 acc = []
#                 for ev in resp:
#                     chunk = getattr(ev, "text", "") or ""
#                     if chunk:
#                         acc.append(chunk)
#                         yield f"data: {json.dumps({'delta': chunk})}\n\n"
#                     else:
#                         yield ': keep-alive\n\n'
#             limiter.on_success()
#             full_answer = strip_source_citations("".join(acc).strip())
#             add_message("assistant", full_answer, session_id=session_id)
#             # Cập nhật Redis context với câu trả lời RAG
#             try:
#                 update_ctx(session_id, "assistant", full_answer)
#             except Exception:
#                 pass
#             yield "event: done\ndata: {}\n\n"
#         except Exception as e:
#             limiter.on_429()
#             yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

#     return Response(
#         stream_with_context(gen()),
#         mimetype="text/event-stream",
#         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
#     )
