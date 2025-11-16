# # routes/chat.py
# # -*- coding: utf-8 -*-
# from __future__ import annotations

# import os
# import re
# import json
# import time
# from pathlib import Path
# from typing import Tuple, Dict, Any, List

# from flask import Blueprint, request, jsonify, session, Response, stream_with_context

# # ===== Project imports (khớp cấu trúc của bạn) =====
# from app.services.history import get_history, add_message, create_new_session
# from app.Helpers.rate_limit import get_text_limiter
# from app.Helpers.prompt_internal import SYSTEM_PRIMER
# from app.Model_LLM.model_llm import LLM_model
# from app.Model_LLM.hybrid_retriever import rerank, TOP_K
# from app.Model_LLM.Query_Supabase.intents import normalize_query
# from app.Model_LLM.Query_Supabase.chat_supabase import handle_message  # service DB
# from app.config.settings import ChatConfig
# from app.Model_LLM.Query_Supabase.sql3 import init_db  # đảm bảo schema (history, session_kv)

# bp = Blueprint("chat", __name__)

# # =============================================================================
# # 0) Dò PROJECT_ROOT & FAISS_DIR chuẩn (fix E:\...\src\src\app\vectorstore\...)
# # =============================================================================
# def _detect_project_root() -> Path:
#     here = Path(__file__).resolve()
#     for parent in here.parents:
#         if (parent / "app").is_dir():
#             return parent
#     return here.parents[2]

# PROJECT_ROOT = _detect_project_root()
# DEFAULT_FAISS_DIR = (PROJECT_ROOT / "app" / "vectorstore" / "FAISS_Vector_All").resolve()
# if not os.getenv("FAISS_DIR"):
#     os.environ["FAISS_DIR"] = str(DEFAULT_FAISS_DIR)

# # =============================================================================
# # 1) DB mặc định + INIT sớm (đảm bảo có bảng lịch sử & KV)
# # =============================================================================
# DEFAULT_DB_PATH = os.getenv(
#     "CHAT_DB_PATH",
#     str((PROJECT_ROOT / "app" / "Data_app" / "chat_history.db").resolve())
# )
# try:
#     init_db(DEFAULT_DB_PATH)
# except Exception:
#     pass

# # =============================================================================
# # 2) Intent DB (đồng bộ với services)
# # =============================================================================
# DB_INTENTS = {
#     "GET_ORDER_COUNT_BY_PERIOD", "GET_TOP_CUSTOMERS_BY_SPEND", "GET_REVENUE_MULTI",
#     "IMPORTED_VN_THIS_PERIOD",
#     "GET_ORDER_STATUS_BY_CODE", "GET_ORDER_STATUS", "GET_ORDER_OWNER",
#     "GET_REVENUE_TOTAL_BY_PERIOD", "GET_REVENUE_BY_SALE", "GET_TOP_STAFF_BY_ORDERS",
#     "GET_TOP_STAFF_PERFORMANCE", "GET_REVENUE_BY_ROUTE", "GET_REVENUE_BY_DESTINATION",
#     "AOV_BY_CUSTOMER", "GET_ORDER_COUNT_BY_STATUS", "CANCEL_RATE", "AVG_FULFILLMENT_TIME",
#     "AVG_RESPONSE_TIME", "AVG_RATING_BY_CUSTOMER", "NEGATIVE_FEEDBACK_CUSTOMERS",
#     "FEEDBACK_COUNT_MONTH", "REPEAT_CUSTOMER_RATE", "TOTAL_COLLECTED_IN_PERIOD",
#     "TOTAL_BY_PAYMENT_METHOD", "CASH_FLOW_DAILY", "TOTAL_OUTSTANDING_IN_PERIOD",
#     "SHIP_PAYMENT_REPORT", "PAYMENT_COUNT_BY_STATUS", "LIST_ORDERS_BY_STATUS",
#     "LIST_WAIT_TO_BUY", "INVENTORY_PARCELS_BY_WAREHOUSE", "AVG_WEIGHT_IN_STOCK",
#     "FLIGHT_WAITING_COUNT", "FLIGHT_COMPLETION_RATE", "AVG_TRANSIT_TIME_FOREIGN_TO_VN"
# }

# # =============================================================================
# # 3) Config helpers (đọc an toàn từ dict/object/None) + GEN_CFG mặc định
# # =============================================================================
# def _cfg_get(cfg, key, default=None):
#     if cfg is None:
#         return default
#     if isinstance(cfg, dict):
#         return cfg.get(key, default)
#     return getattr(cfg, key, default)

# try:
#     from google.generativeai.types import GenerateContentConfig as _GenCfg
#     DEFAULT_GEN_CFG = _GenCfg(max_output_tokens=1024, temperature=0.2, top_p=0.95, top_k=40)
# except Exception:
#     class _ShimCfg:
#         def __init__(self, **kw):
#             for k, v in kw.items():
#                 setattr(self, k, v)
#     DEFAULT_GEN_CFG = _ShimCfg(max_output_tokens=1024, temperature=0.2, top_p=0.95, top_k=40)

# def _unpack_llm_model(ret):
#     """
#     LLM_model():
#       - Nếu trả 6 phần tử: (emb, store, retr, gclient, model, cfg) → dùng luôn
#       - Nếu trả 5 phần tử: (emb, store, retr, gclient, model) → bù DEFAULT_GEN_CFG
#     """
#     if not isinstance(ret, (list, tuple)):
#         raise ValueError("LLM_model() must return tuple/list.")
#     if len(ret) >= 6:
#         return ret[:6]
#     if len(ret) == 5:
#         emb, store, retr, gclient, model = ret
#         return emb, store, retr, gclient, model, DEFAULT_GEN_CFG
#     raise ValueError(f"Unexpected LLM_model() return length: {len(ret)}")

# # =============================================================================
# # 4) Router: DB hay RAG?
# # =============================================================================
# def _should_go_database(user_text: str) -> tuple[bool, dict]:
#     rag_keywords = (
#         "bồi thường", "chính sách", "policy", "quy định", "điều khoản",
#         "giá đường air", "giá vận chuyển", "điều lệ", "hướng dẫn", "air japan"
#     )
#     try:
#         parsed = normalize_query(user_text)
#         intent = (parsed or {}).get("intent") or ""
#         text_l = (user_text or "").lower()

#         if any(k in text_l for k in rag_keywords):
#             return (False, parsed)
#         if intent in ("SMALLTALK", "UNKNOWN", "", None):
#             return (False, parsed)
#         return (intent in DB_INTENTS, parsed)
#     except Exception:
#         return (False, {"intent": "UNKNOWN", "norm": {}})

# # =============================================================================
# # 5) Gemini helpers (không dùng .get trên object)
# # =============================================================================
# LLM_SEM = ChatConfig.LLM_SEM  # Semaphore chống spam

# def _estimate_from_contents(contents: List[Dict[str, Any]], max_out_tokens: int = 1024) -> int:
#     words = 0
#     for m in contents or []:
#         for p in (m.get("parts") or []):
#             if isinstance(p, dict) and p.get("text"):
#                 words += len(p["text"].split())
#     return int(1.3 * words) + int(max_out_tokens or 512)

# def _safe_gemini_generate(gclient, model: str, contents: List[Dict[str, Any]], config,  # config: dict | object | None
#                           retries: int = 3, backoff: float = 0.4) -> Tuple[str, float]:
#     limiter = get_text_limiter()
#     max_out = _cfg_get(config, "max_output_tokens", 1024)
#     tokens_est = _estimate_from_contents(contents, max_out)
#     last_err = None
#     t0 = time.time()
#     for i in range(retries + 1):
#         try:
#             limiter.acquire(tokens_est)
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(
#                     model=model,
#                     contents=contents,
#                     config=(config or DEFAULT_GEN_CFG)
#                 )
#             limiter.on_success()
#             txt = (getattr(resp, "text", "") or "").strip()
#             return txt, (time.time() - t0)
#         except Exception as e:
#             last_err = e
#             s = str(e).lower()
#             if ("429" in s or "quota" in s or "rate" in s) and i < retries:
#                 limiter.on_429()
#                 time.sleep(backoff * (2 ** i))
#                 continue
#             limiter.on_429()
#             raise last_err

# _SOURCE_TAG_PAT = re.compile(
#     r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
#     re.IGNORECASE
# )

# def strip_source_citations(text: str) -> str:
#     if not text:
#         return text
#     text = _SOURCE_TAG_PAT.sub("", text)
#     text = re.sub(r"[ \t]{2,}", " ", text)
#     text = re.sub(r"\s+([,.;:!?])", r"\1", text)
#     return text.strip()

# def _to_gemini_history_no_system(history_msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
#     out: List[Dict[str, Any]] = []
#     for m in history_msgs or []:
#         role = m.get("role", "user")
#         content = (m.get("content") or "").strip()
#         if not content:
#             continue
#         out.append({
#             "role": ("model" if role == "assistant" else "user"),
#             "parts": [{"text": content}]
#         })
#     return out

# # =============================================================================
# # 6) REST: /api/chat (JSON) — auto route DB/RAG
# # =============================================================================
# @bp.route("/api/chat", methods=["POST"])
# def chat_api():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = _unpack_llm_model(LLM_model())

#     data = request.get_json(force=True) or {}
#     user_text  = (data.get("message") or "").strip()
#     session_id = (data.get("session_id") or "").strip()
#     forced_mode = (data.get("mode") or "").strip().lower()   # 'db'|'rag'|''

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or ""
#         except Exception:
#             session_id = session_id or ""

#     add_message("user", user_text, session_id=session_id)

#     is_db, _parsed = _should_go_database(user_text)
#     if forced_mode == "db":
#         is_db = True
#     elif forced_mode == "rag":
#         is_db = False

#     # ======================= DATABASE PATH =======================
#     if is_db:
#         full_start = time.time()
#         db_path = (data.get("db_path") or "").strip() or DEFAULT_DB_PATH

#         try:
#             init_db(db_path)  # init mỗi request theo file
#         except Exception:
#             pass

#         try:
#             svc_res = handle_message(user_text, session_id=session_id, db_path=db_path)
#             answer = (svc_res or {}).get("reply") or ""
#         except Exception as e:
#             svc_res = None
#             answer = f"Lỗi khi lấy dữ liệu: {e}"

#         add_message("assistant", answer, session_id=session_id)
#         elapsed = round(time.time() - full_start, 2)

#         return jsonify({
#             "ok": True,
#             "mode": "database",
#             "session_id": session_id,
#             "answer": answer,
#             "table": (svc_res or {}).get("table"),
#             "chart": (svc_res or {}).get("chart"),
#             "meta":  (svc_res or {}).get("meta"),
#             "timing": {"total": elapsed}
#         })

#     # ========================= RAG PATH ==========================
#     full_start = time.time()

#     # 1) embed
#     try:
#         t0 = time.time()
#         _ = embeddings.embed_query("query: " + user_text)
#         embed_time = round(time.time() - t0, 2)
#     except Exception:
#         embed_time = 0.0

#     # 2) retrieve + rerank
#     docs_text, search_time = "", 0.0
#     try:
#         t0 = time.time()
#         cands = retriever.get_relevant_documents("query: " + user_text)
#         ranked = rerank(user_text, cands, top_k=TOP_K)
#         parts, total = [], 0
#         for d, _score in ranked:
#             txt = d.page_content or ""
#             if txt.lower().startswith("passage: "):
#                 txt = txt[len("passage: "):]
#             parts.append(txt)
#             total += len(txt)
#             if total > 4000:
#                 break
#         docs_text = "\n\n---\n\n".join(parts) if parts else ""
#         search_time = round(time.time() - t0, 2)
#     except Exception:
#         pass

#     context_hint = f"Context (trích từ tài liệu):\n{docs_text}" if docs_text else "(Không tìm thấy dữ liệu context phù hợp.)"
#     system_prompt = f"""{SYSTEM_PRIMER}
# {context_hint}
# """

#     hist_msgs = [{"role": m["role"], "content": m["content"]} for m in get_history() if m["role"] in ("user", "assistant")]
#     contents = _to_gemini_history_no_system(hist_msgs)
#     first_user = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user}]})

#     try:
#         result_text, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     except Exception as e:
#         result_text, llm_time = f"Lỗi khi gọi Gemini API: {e}", 0.0

#     result_text = strip_source_citations(result_text)
#     add_message("assistant", result_text, session_id=session_id)

#     total_time = round(time.time() - full_start, 2)
#     return jsonify({
#         "ok": True,
#         "mode": "rag",
#         "session_id": session_id,
#         "answer": result_text,
#         "timing": {
#             "total": total_time,
#             "embedding": embed_time,
#             "search": search_time,
#             "llm": round(llm_time, 2)
#         }
#     })

# # =============================================================================
# # 7) REST: /api/chat/stream (SSE)
# # =============================================================================
# @bp.route("/api/chat/stream", methods=["POST"])
# def chat_stream():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = _unpack_llm_model(LLM_model())

#     data = request.get_json(force=True) or {}
#     user_text  = (data.get("message") or "").strip()
#     session_id = (data.get("session_id") or "").strip()
#     forced_mode = (data.get("mode") or "").strip().lower()   # 'db'|'rag'|''

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or ""
#         except Exception:
#             session_id = session_id or ""

#     add_message("user", user_text, session_id=session_id)

#     is_db, _parsed = _should_go_database(user_text)
#     if forced_mode == "db":
#         is_db = True
#     elif forced_mode == "rag":
#         is_db = False

#     # ============ STREAM – DATABASE ============
#     if is_db:
#         def gen_db():
#             yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'mode':'database'})}\n\n"
#             try:
#                 db_path = (data.get("db_path") or "").strip() or DEFAULT_DB_PATH
#                 try:
#                     init_db(db_path)
#                 except Exception:
#                     pass

#                 svc_res = handle_message(user_text, session_id=session_id, db_path=db_path)
#                 answer = (svc_res or {}).get("reply") or ""
#                 add_message("assistant", answer, session_id=session_id)
#                 yield f"data: {json.dumps({'delta': answer})}\n\n"
#                 yield "event: done\ndata: {}\n\n"
#             except Exception as e:
#                 yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

#         return Response(
#             stream_with_context(gen_db()),
#             mimetype="text/event-stream",
#             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
#         )

#     # ============== STREAM – RAG ==============
#     hist_msgs = [{"role": m["role"], "content": m["content"]} for m in get_history() if m["role"] in ("user", "assistant")]
#     contents = _to_gemini_history_no_system(hist_msgs)
#     system_prompt = f"""{SYSTEM_PRIMER}
# (Stream mode - context omitted)
# """
#     first_user = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user}]})

#     limiter = get_text_limiter()
#     tokens_est = _estimate_from_contents(contents, _cfg_get(GEN_CFG, "max_output_tokens", 1024))

#     def gen_rag():
#         yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'mode':'rag'})}\n\n"
#         try:
#             limiter.acquire(tokens_est)
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(
#                     model=GEMINI_MODEL,
#                     contents=contents,
#                     config=(GEN_CFG or DEFAULT_GEN_CFG),
#                     stream=True
#                 )
#                 acc = []
#                 for ev in resp:
#                     chunk = getattr(ev, "text", "") or ""
#                     if chunk:
#                         acc.append(chunk)
#                         yield f"data: {json.dumps({'delta': chunk})}\n\n"
#                     else:
#                         yield ": keep-alive\n\n"
#             limiter.on_success()
#             full_text = strip_source_citations("".join(acc).strip())
#             add_message("assistant", full_text, session_id=session_id)
#             yield "event: done\ndata: {}\n\n"
#         except Exception as e:
#             limiter.on_429()
#             yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

#     return Response(
#         stream_with_context(gen_rag()),
#         mimetype="text/event-stream",
#         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
#     )

# # =============================================================================
# # 8) Alias route (nếu client cũ vẫn gọi /chat)
# # =============================================================================
# @bp.route("/chat", methods=["POST"])
# def chat_api_alias():
#     return chat_api()
