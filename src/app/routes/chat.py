import time, json, re
from flask import Blueprint, request, jsonify, session, Response, stream_with_context
from app.Helpers.rate_limit import get_text_limiter
from app.services.history import get_history, add_message, create_new_session
from app.Helpers.prompt_internal import SYSTEM_PRIMER
from app.Model_LLM.model_llm import LLM_model
from app.Helpers.prompt_KT import persona_vi
from app.Model_LLM.hybrid_retriever import rerank, TOP_K
from app.config.settings import ChatConfig

bp = Blueprint('chat', __name__)

# ====== LLM helpers kept local to this module ======
LLM_SEM = ChatConfig.LLM_SEM

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
        
_SOURCE_TAG_PAT = re.compile(r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]", re.IGNORECASE)

def strip_source_citations(text: str) -> str:
    if not text:
        return text
    text = _SOURCE_TAG_PAT.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\\1", text)
    return text.strip()

def _to_gemini_history_no_system(history_msgs):
    out = []
    for m in history_msgs:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            role = "model"
        else:
            role = "user"
        out.append({"role": role, "parts": [{"text": content}]})
    return out

@bp.route('/api/chat', methods=['POST'])
def chat_api():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()

    data = request.get_json(force=True) or {}
    user_text  = (data.get('message') or "").strip()
    session_id = (data.get('session_id') or "").strip()
    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    # Nếu client không gửi session_id -> server tạo phiên MỚI ngay bây giờ
    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
            session_id = info.get("session_id") or ""
        except Exception:
            # fallback: vẫn để rỗng, add_message sẽ tự tạo theo logic bạn đã sửa
            pass

    # Lưu user message (dùng đúng session_id vừa tạo ở trên)
    add_message("user", user_text, session_id=session_id)
    full_start = time.time()
    
    # 1) embed
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
                txt = txt[len("passage: "):]
            parts.append(txt)
            total += len(txt)
            if total > 4000:
                break
        docs_text = "\n\n---\n\n".join(parts) if parts else ""
        search_time = time.time() - t0
    except Exception:
        pass

    context_hint = f"Context (trích từ tài liệu):\n{docs_text}" if docs_text else "(Không tìm thấy dữ liệu context phù hợp.)"
    system_prompt = f"""{SYSTEM_PRIMER}
    {context_hint}
    """

    hist_msgs = [{"role": m["role"], "content": m["content"]} for m in get_history() if m["role"] in ("user", "assistant")]
    contents = _to_gemini_history_no_system(hist_msgs)
    first_user_text = f"""[SYSTEM]
    {system_prompt}

    [USER]
    {user_text}"""
    contents.append({"role": "user", "parts": [{"text": first_user_text}]})

    try:
        result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    except Exception as e:
        result = f"Lỗi khi gọi Gemini API: {e}"
        llm_time = 0.0

    result = strip_source_citations(result)

    # Lưu assistant message vào ĐÚNG session_id
    add_message("assistant", result, session_id=session_id)
    elapsed = time.time() - full_start

    # ⇨ TRẢ VỀ session_id CHO UI
    return jsonify({
        "ok": True,
        "answer": result,
        "session_id": session_id,
        "timing": {
            "total": round(elapsed, 2),
            "embedding": round(embed_time, 2),
            "search": round(search_time, 2),
            "llm": round(llm_time, 2)
        }
    })


    
@bp.route('/chat', methods=['POST'])
def chat_api_alias():
    return chat_api()

@bp.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()

    data = request.get_json(force=True) or {}
    user_text  = (data.get('message') or "").strip()
    session_id = (data.get('session_id') or "").strip()
    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    # Nếu client không gửi session_id -> server tạo phiên MỚI ngay bây giờ
    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
            session_id = info.get("session_id") or ""
        except Exception:
            pass

    # Lưu user message trước khi stream
    add_message("user", user_text, session_id=session_id)

    hist_msgs = [{"role": m["role"], "content": m["content"]} for m in get_history() if m["role"] in ("user", "assistant")]
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
    tokens_est = _estimate_from_contents(contents, GEN_CFG.get("max_output_tokens", 1024))
    
    def gen():
      # gửi ngay session_id để UI lưu
      yield f"event: ready\ndata: {json.dumps({'session_id': session_id})}\n\n"
      try:
          limiter.acquire(tokens_est)
          with LLM_SEM:
              resp = gclient.models.generate_content(model=GEMINI_MODEL, contents=contents, config=GEN_CFG, stream=True)
              acc = []
              for ev in resp:
                  chunk = getattr(ev, "text", "") or ""
                  if chunk:
                      acc.append(chunk)
                      yield f"data: {json.dumps({'delta': chunk})}\n\n"
                  else:
                      yield ': keep-alive\n\n'
          limiter.on_success()
          full_answer = "".join(acc).strip()
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
