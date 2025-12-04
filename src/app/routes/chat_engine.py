# from __future__ import annotations
# import os
# import re
# import time
# import json
# from typing import List, Dict, Any, Tuple, Optional
# import fitz
# import docx as docx_lib
# import unicodedata
# from pathlib import Path
# from langchain_core.documents import Document
# from langchain_community.vectorstores import FAISS
# from flask import session
# from app.services.history import get_history, add_message, create_new_session
# from app.Helpers.prompt_internal import SYSTEM_PRIMER, sys_instr
# from app.Model_LLM.model_llm import LLM_model
# from app.Model_LLM.hybrid_retriever import rerank, TOP_K
# from app.config.settings import ChatConfig, Chat_engine
# from app.Model_LLM.Chat_Database.db_router import handle_db_message
# from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx, redis_client
# from app.config.paths import DATA_DIR, FAISS_ALL_DIR

# LLM_SEM = ChatConfig.LLM_SEM
# DB_CONF_THRESHOLD = Chat_engine.DB_CONF_THRESHOLD
# REWRITE_DB_WITH_LLM = Chat_engine.REWRITE_DB_WITH_LLM
# SESSION_DOC_VS: Dict[str, FAISS] = {}
# SESSION_DOC_SUMMARY: Dict[str, str] = {}

# # ======================================================================
# # 1. HISTORY / CTX HELPERS
# # ======================================================================
# def _normalize_vi(text: str) -> str:
#     if not text:
#         return ""
#     text = unicodedata.normalize("NFD", text)
#     text = "".join(ch for ch in text if not unicodedata.combining(ch))
#     return text


# def _get_history_msgs_for_ctx() -> List[Dict[str, str]]:
#     try:
#         hist = [
#             {"role": m["role"], "content": m["content"]}
#             for m in get_history()
#             if m["role"] in ("user", "assistant")
#         ]
#     except Exception:
#         hist = []
#     return hist


# def _get_last_assistant_message(history_msgs: List[Dict[str, str]]) -> Optional[str]:
#     for m in reversed(history_msgs or []):
#         if m.get("role") == "assistant":
#             content = (m.get("content") or "").strip()
#             if content:
#                 return content
#     return None


# def _load_ctx(session_id: str) -> Dict[str, Any]:
#     try:
#         ctx = get_ctx(session_id) or {}
#         if not isinstance(ctx, dict):
#             return {}
#         return ctx
#     except Exception:
#         return {}


# # ======================================================================
# # 2. DETECT NGÔN NGỮ ĐƠN GIẢN
# # ======================================================================
# def _auto_detect_lang(text: str) -> str:
#     text = text or ""

#     vi_chars = re.findall(
#         r"[àáạảãăằắặẳẵâầấậẩẫèéẹẻẽêềếệểễ"
#         r"ìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũư"
#         r"ừứựửữỳýỵỷỹđÀÁẠẢÃĂẰẮẶẲẴÂẦẤẬẨẪ"
#         r"ÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠ"
#         r"ỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]",
#         text,
#     )
#     if len(vi_chars) >= 1:
#         return "vi"

#     if re.search(r"[A-Za-z]", text):
#         return "en"

#     return "vi"

# def _make_summary_key(session_id: str, path: str) -> str:
#     basename = os.path.basename(path)
#     try:
#         mtime = int(os.path.getmtime(path))
#     except Exception:
#         mtime = 0
#     return f"file_summary:{session_id}:{basename}:{mtime}"


# # ======================================================================
# # 3. EDITOR: DỊCH/VIẾT LẠI CÂU TRẢ LỜI TRƯỚC
# # ======================================================================
# def _contents_to_ollama_messages(contents):
#     msgs = []
#     for m in contents or []:
#         role = m.get("role", "user")
#         if role not in ("user", "assistant", "system"):
#             role = "user"

#         text_parts = []
#         for p in m.get("parts") or []:
#             if isinstance(p, dict) and p.get("text"):
#                 text_parts.append(p["text"])
#         if not text_parts:
#             continue

#         msgs.append({"role": role, "content": "\n".join(text_parts)})
#     return msgs


# def _estimate_from_contents(contents, max_out_tokens=1024) -> int:
#     words = 0
#     for m in contents or []:
#         for p in (m.get("parts") or []):
#             if isinstance(p, dict) and p.get("text"):
#                 words += len(p["text"].split())
#     return int(1.3 * words) + int(max_out_tokens or 512)


# def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
#     from app.Helpers.rate_limit import get_text_limiter

#     limiter = get_text_limiter()
#     max_out = (
#         config.get("max_output_tokens")
#         if isinstance(config, dict)
#         else getattr(config, "max_output_tokens", 1024)
#     )
#     tokens_est = _estimate_from_contents(contents, max_out)
#     last_err: Optional[Exception] = None

#     for i in range(retries + 1):
#         try:
#             limiter.acquire(tokens_est)
#             t0 = time.time()
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(
#                     model=model, contents=contents, config=config
#                 )
#             limiter.on_success()
#             return (getattr(resp, "text", "") or ""), time.time() - t0
#         except Exception as e:
#             last_err = e
#             s = str(e).lower()
#             if ("429" in s or "quota" in s or "resource_exhausted" in s) and i < retries:
#                 limiter.on_429()
#                 time.sleep(backoff * (2**i))
#                 continue
#             limiter.on_429()
#             raise last_err


# def _rewrite_last_answer_for_lang(
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     last_answer: str,
#     target_lang: str = "en",
# ) -> str:
#     last_answer = (last_answer or "").strip()
#     if not last_answer:
#         return ""

#     target_lang = (target_lang or "en").lower()

#     if target_lang.startswith("en"):
#         instr = (
#             "Rewrite the following answer in clear, natural English. "
#             "Keep the meaning and important details, but you can shorten slightly if needed.\n"
#             "Answer ONLY in English.\n"
#         )
#     else:
#         instr = (
#             "Viết lại câu trả lời sau bằng tiếng Việt rõ ràng, tự nhiên. "
#             "Giữ nguyên ý chính và các chi tiết quan trọng, có thể rút gọn nhẹ nếu cần.\n"
#             "Chỉ trả lời bằng tiếng Việt.\n"
#         )

#     prompt = f"""{instr}
#     [ANSWER]
#     {last_answer}
#     """

#     contents = [
#         {
#             "role": "user",
#             "parts": [{"text": prompt}],
#         }
#     ]

#     out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     return (out or "").strip()


# def _analyze_followup_and_lang(
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     user_text: str,
#     history_msgs: List[Dict[str, str]],
#     ctx: Dict[str, Any],
# ):
#     user_text = (user_text or "").strip()
#     if not user_text:
#         return {"mode": "pass", "output": "", "set_lang": None}

#     last_ans = _get_last_assistant_message(history_msgs)
#     if not last_ans:
#         return {"mode": "pass", "output": "", "set_lang": None}

#     current_lang = (ctx or {}).get("lang") or "vi"
#     lower_ut = user_text.lower()

#     vi_to_en_patterns = [
#         "viết bằng tiếng anh",
#         "viết lại bằng tiếng anh",
#         "viết tiếng anh",
#         "dịch sang tiếng anh",
#         "dịch đoạn trên sang tiếng anh",
#         "dịch nội dung trên sang tiếng anh",
#         "rewrite in english",
#         "write in english",
#         "answer in english",
#         "translate to english",
#     ]
#     en_to_vi_patterns = [
#         "viết bằng tiếng việt",
#         "viết lại bằng tiếng việt",
#         "dịch sang tiếng việt",
#         "dịch đoạn trên sang tiếng việt",
#         "dịch nội dung trên sang tiếng việt",
#         "rewrite in vietnamese",
#         "translate to vietnamese",
#     ]

#     if any(p in lower_ut for p in vi_to_en_patterns):
#         out_text = _rewrite_last_answer_for_lang(
#             gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="en"
#         )
#         return {
#             "mode": "edit",
#             "output": out_text,
#             "set_lang": "en",
#         }

#     if any(p in lower_ut for p in en_to_vi_patterns):
#         out_text = _rewrite_last_answer_for_lang(
#             gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="vi"
#         )
#         return {
#             "mode": "edit",
#             "output": out_text,
#             "set_lang": "vi",
#         }

#     prompt = f"""{sys_instr}

#     [CURRENT_PREFERRED_LANG]
#     {current_lang}

#     [PREVIOUS_ANSWER]
#     {last_ans}

#     [USER_REQUEST]
#     {user_text}
#     """

#     contents = [
#         {
#             "role": "user",
#             "parts": [{"text": prompt}],
#         }
#     ]

#     raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     raw = (raw or "").strip()

#     try:
#         data = json.loads(raw)
#     except Exception:
#         data = {}

#     if not isinstance(data, dict):
#         data = {}

#     mode = (data.get("mode") or "pass").lower()
#     output = (data.get("output") or "").strip()
#     set_lang = data.get("set_lang", None)

#     if set_lang is not None:
#         if isinstance(set_lang, str):
#             set_lang = set_lang.lower()
#             if set_lang not in ("vi", "en"):
#                 set_lang = None
#         else:
#             set_lang = None

#     if set_lang is None:
#         detected = _auto_detect_lang(user_text)
#         if detected in ("vi", "en") and detected != current_lang:
#             set_lang = detected

#     if mode != "edit" or not output:
#         return {"mode": "pass", "output": "", "set_lang": set_lang}

#     return {"mode": "edit", "output": output, "set_lang": set_lang}


# # ======================================================================
# # 4. FILE UPLOAD (VS session) + STRIP SOURCE
# # ======================================================================
# def strip_source_citations(text: str) -> str:
#     if not text:
#         return text

#     # Mở rộng pattern để match cả (Nguồn: ...) và các biến thể có dấu ngoặc, backslash, lỗi chính tả như "Biễu"
#     text = re.sub(
#         r'\s*\(?\s*[Nn]gu[oơ]n\s*:\s*[^\n\)]*\.(?:txt|docx|pdf)\s*\)?',
#         '',
#         text,
#         flags=re.IGNORECASE | re.DOTALL,
#     )

#     # Loại bỏ các pattern khác như cũ, nhưng mở rộng để match path có backslash
#     text = re.sub(
#         r'\bsource["\']?\s*:\s*["\']?[^"\n]*\.(?:txt|docx|pdf)["\']?',
#         '',
#         text,
#         flags=re.IGNORECASE,
#     )

#     text = re.sub(
#         r'[\(\[\{]\s*(?:source|chunk_id|metadata|norm_case|Nguồn)[\s:][^\)\]\}]{0,400}[\)\]\}]',
#         '',
#         text,
#         flags=re.IGNORECASE,
#     )

#     text = re.sub(
#         r'\(\s*[Ll]ink\s*:\s*(?!https?://)[^)]*\.(?:txt|docx|pdf)\s*\)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     text = re.sub(
#         r'\b[Ll]ink\s*:\s*(?!https?://)[^\n]*\.(?:txt|docx|pdf)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     text = re.sub(
#         r'\b[Nn]gu[oơ]n\s*:\s*[^\n]*\.(?:txt|docx|pdf)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     # Loại bỏ các path internal như Accountant\folder\file.txt
#     text = re.sub(
#         r'\(Accountant\\[^\)]*\.(?:txt|docx|pdf)\)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     text = re.sub(r'[ \t]{2,}', ' ', text)
#     text = re.sub(r'\s+([.,!?;:])', r'\1', text)
#     text = re.sub(r'\(\s*\)', '', text)
#     text = re.sub(r'\.{3,}', '...', text)
#     text = text.strip()

#     return text


# def _extract_text_from_uploaded_file(path: str) -> str:
#     ext = os.path.splitext(path)[1].lower()

#     if ext == ".txt":
#         try:
#             with open(path, "r", encoding="utf-8") as f:
#                 return f.read()
#         except Exception:
#             return ""

#     if ext == ".docx":
#         try:
#             d = docx_lib.Document(path)
#             lines = []
#             for p in d.paragraphs:
#                 t = (p.text or "").strip()
#                 if t:
#                     lines.append(t)
#             for tbl in d.tables:
#                 for row in tbl.rows:
#                     cells = [(cell.text or "").strip() for cell in row.cells]
#                     line = " | ".join(c for c in cells if c)
#                     if line:
#                         lines.append(line)
#             return "\n".join(lines)
#         except Exception:
#             return ""

#     if ext == ".pdf":
#         try:
#             doc = fitz.open(path)
#             pages = []
#             for p in doc:
#                 t = p.get_text()
#                 if t.strip():
#                     pages.append(t)
#             doc.close()
#             return "\n".join(pages)
#         except Exception:
#             return ""

#     return ""
# def _summarize_uploaded_file(
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     path: str,
#     max_lines: int = 10,
# ) -> str:
#     raw_text = _extract_text_from_uploaded_file(path)
#     if not raw_text.strip():
#         return ""

#     detected_lang = _auto_detect_lang(raw_text)

#     prompt = f"""Tóm tắt tài liệu sau thành khoảng {max_lines} dòng chính.
# - Giữ nguyên số liệu quan trọng, mã số, tên riêng, bảng biểu (dùng định dạng ASCII nếu cần).
# - Tập trung vào nội dung cốt lõi, cấu trúc, ý chính.
# - Bỏ chi tiết thừa, lặp lại.
# - Trả lời bằng tiếng {'Việt' if detected_lang == 'vi' else 'Anh'}.

# [TÀI LIỆU]
# {raw_text[:1500]}  # Giới hạn để tránh quá dài
# """  # Giảm từ 20000 xuống 15000 để an toàn

#     contents = [{"role": "user", "parts": [{"text": prompt}]}]
#     try:
#         summary, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#         return summary.strip() or raw_text[:2000]
#     except Exception:
#         return raw_text[:2000]


# def _split_text_to_chunks(text: str, max_chars: int = 800, overlap: int = 200) -> List[str]:
#     text = (text or "").strip()
#     if not text:
#         return []

#     chunks: List[str] = []
#     start = 0
#     n = len(text)
#     while start < n:
#         end = min(start + max_chars, n)
#         chunk = text[start:end].strip()
#         if chunk:
#             chunks.append(chunk)
#         if end == n:
#             break
#         start = max(0, end - overlap)
#     return chunks

# SESSION_DOC_VS: Dict[str, FAISS] = {}
# SESSION_DOC_VS_META: Dict[str, Dict[str, float]] = {}

# def _build_session_doc_vs(
#     session_id: str,
#     embeddings,
#     file_paths: List[str],
# ) -> Optional[FAISS]:
#     if not session_id or not file_paths:
#         return None

#     texts: List[str] = []
#     metas: List[Dict[str, Any]] = []

#     for path in file_paths:
#         if not path or not os.path.exists(path):
#             continue
#         try:
#             raw = _extract_text_from_uploaded_file(path)
#         except Exception:
#             raw = ""
#         if not raw.strip():
#             continue

#         chunks = _split_text_to_chunks(raw, max_chars=800, overlap=200)
#         src = os.path.basename(path)
#         for ch in chunks:
#             texts.append(ch)
#             metas.append({"source": src, "session_id": session_id})

#     if not texts:
#         return None

#     vs = FAISS.from_texts(texts, embeddings, metadatas=metas)

#     # 🔹 Lưu cả VS và meta file (path + mtime)
#     SESSION_DOC_VS[session_id] = vs
#     meta_map: Dict[str, float] = {}
#     for p in file_paths:
#         if p and os.path.exists(p):
#             meta_map[p] = os.path.getmtime(p)
#     SESSION_DOC_VS_META[session_id] = meta_map

#     return vs


# # ======================================================================
# # SỬA LẠI _get_session_doc_vs ĐỂ FIX LỖI DECODE (an toàn với bytes/string từ Redis)
# # ======================================================================
# def _get_session_doc_vs(
#     session_id: str,
#     embeddings,
#     file_paths: List[str],
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
# ) -> Optional[FAISS]:
#     """
#     Xây / lấy lại FAISS vectorstore cho các file đã upload trong 1 session.

#     - Dùng meta (path → mtime) để quyết định có reuse VS hay không.
#     - Nếu meta đổi → xóa VS cũ + meta cũ + toàn bộ summary cũ của session.
#     - Summary được cache riêng theo (session, basename, mtime).
#     """
#     if not session_id or not file_paths:
#         return None

#     # ================================================================
#     # 1. Tính meta hiện tại: path → mtime
#     # ================================================================
#     current_meta: Dict[str, float] = {}
#     for p in file_paths:
#         if os.path.exists(p):
#             try:
#                 current_meta[p] = os.path.getmtime(p)
#             except Exception:
#                 continue

#     # Nếu không có file nào tồn tại trên đĩa → không build VS
#     if not current_meta:
#         # Invalidate luôn cache nếu trước đó có
#         SESSION_DOC_VS.pop(session_id, None)
#         SESSION_DOC_VS_META.pop(session_id, None)
#         try:
#             redis_client.delete(f"session_doc_vs_meta:{session_id}")
#             keys = redis_client.keys(f"file_summary:{session_id}:*")
#             if keys:
#                 redis_client.delete(*keys)
#         except Exception:
#             pass
#         return None

#     # ================================================================
#     # 2. Đọc meta đã cache trong Redis (decode_responses=True → luôn là str)
#     # ================================================================
#     cached_meta_key = f"session_doc_vs_meta:{session_id}"
#     cached_meta_str = redis_client.get(cached_meta_key)  # None hoặc str JSON

#     cached_meta: Dict[str, float] = {}
#     if cached_meta_str:
#         try:
#             cached_meta = json.loads(cached_meta_str)
#         except json.JSONDecodeError:
#             cached_meta = {}

#     # ================================================================
#     # 3. So sánh meta: nếu giống hệt → dùng lại VS từ RAM nếu có
#     # ================================================================
#     same_meta = bool(cached_meta) and (cached_meta == current_meta)

#     if same_meta and session_id in SESSION_DOC_VS:
#         return SESSION_DOC_VS[session_id]

#     # ================================================================
#     # 4. Nếu meta KHÁC → invalidate cache cũ (VS + meta + summary)
#     # ================================================================
#     if not same_meta:
#         # Xóa VS cũ trong RAM
#         SESSION_DOC_VS.pop(session_id, None)
#         SESSION_DOC_VS_META.pop(session_id, None)

#         # Xóa meta cũ trong Redis
#         try:
#             redis_client.delete(cached_meta_key)
#         except Exception:
#             pass

#         # Xóa toàn bộ summary cũ của session
#         try:
#             keys = redis_client.keys(f"file_summary:{session_id}:*")
#             if keys:
#                 redis_client.delete(*keys)
#         except Exception:
#             pass

#     # ================================================================
#     # 5. Build VS mới từ danh sách file hiện tại (dùng summary)
#     # ================================================================
#     texts: List[str] = []
#     metas: List[Dict[str, Any]] = []

#     for path in file_paths:
#         if not os.path.exists(path):
#             continue

#         # ----- Lấy summary từ Redis với key có mtime -----
#         summary_key = _make_summary_key(session_id, path)
#         summary = redis_client.get(summary_key)  # None hoặc str

#         # ----- Nếu chưa có summary hoặc rỗng → tóm tắt mới -----
#         if not summary or not summary.strip():
#             summary = _summarize_uploaded_file(
#                 gclient=gclient,
#                 GEMINI_MODEL=GEMINI_MODEL,
#                 GEN_CFG=GEN_CFG,
#                 path=path,
#             )
#             if summary:
#                 try:
#                     # decode_responses=True nên set thẳng str
#                     redis_client.set(
#                         summary_key,
#                         summary,
#                         ex=86400,  # 1 ngày
#                     )
#                 except Exception:
#                     # Không để lỗi Redis làm hỏng flow chính
#                     pass

#         if not summary or not summary.strip():
#             continue

#         # ----- Chunk summary để index vào FAISS -----
#         chunks = _split_text_to_chunks(summary, max_chars=500, overlap=100)
#         src = os.path.basename(path)

#         for ch in chunks:
#             texts.append(ch)
#             metas.append(
#                 {
#                     "source": src,
#                     "session_id": session_id,
#                     "is_summary": True,
#                 }
#             )

#     # Nếu không có gì để index → trả None + dọn meta
#     if not texts:
#         SESSION_DOC_VS.pop(session_id, None)
#         SESSION_DOC_VS_META.pop(session_id, None)
#         try:
#             redis_client.delete(cached_meta_key)
#         except Exception:
#             pass
#         return None

#     # Build VS mới
#     vs = FAISS.from_texts(texts, embeddings, metadatas=metas)
#     SESSION_DOC_VS[session_id] = vs
#     SESSION_DOC_VS_META[session_id] = current_meta

#     # Cache lại meta mới vào Redis
#     try:
#         meta_json = json.dumps(current_meta)
#         redis_client.set(
#             cached_meta_key,
#             meta_json,
#             ex=86400,  # 1 ngày
#         )
#     except Exception:
#         pass

#     return vs


# def _clear_session_doc_vs(session_id: str) -> None:
#     SESSION_DOC_VS.pop(session_id, None)
#     SESSION_DOC_VS_META.pop(session_id, None)
    
#     redis_client.delete(f"session_doc_vs_meta:{session_id}")
#     keys = redis_client.keys(f"file_summary:{session_id}:*")
#     if keys:
#         redis_client.delete(*keys)



# def _extract_src_and_url(meta: dict) -> tuple[str, str]:
#     if not isinstance(meta, dict):
#         return "", ""

#     src_name = (
#         meta.get("title")
#         or meta.get("source")
#         or meta.get("filename")
#         or ""
#     )

#     url = meta.get("url") or meta.get("link") or meta.get("path") or ""

#     if "http" not in url and (src_name.endswith(('.txt', '.docx', '.pdf')) or '\\' in src_name):
#         src_name = ""

#     return src_name or "", url or ""

# def _is_query_about_uploaded_file(
#     user_text: str,
#     lang: str = "vi",
#     gclient=None,
#     GEMINI_MODEL=None,
#     GEN_CFG=None,
# ) -> bool:
#     """
#     Dùng Gemini để quyết định: người dùng có đang hỏi về file đã upload không?
#     Chỉ gọi 1 lần LLM → chính xác 99.9%, không cần keyword.
#     """
#     if not gclient or not user_text.strip():
#         return False

#     # Nếu câu quá dài (>400 ký tự) → cắt ngắn để tiết kiệm token
#     query = user_text.strip()[:15000]

#     prompt = f"""Bạn là chuyên gia phân tích ngữ cảnh chat.
#     Có file đã được upload trong phiên này.
#     Người dùng có đang hỏi cụ thể về nội dung của file đó không?

#     Chỉ trả lời đúng 1 từ: YES hoặc NO. Không giải thích.

#     Ví dụ:
#     - "tóm tắt" → YES
#     - "nội dung file trên" → YES
#     - "cái này nói gì" → YES
#     - "file này là gì" → YES
#     - "quy trình nghỉ phép mới nhất?" → NO
#     - "lương tháng này bao nhiêu?" → NO

#     Câu hỏi người dùng: {query}

#     Trả lời:"""

#     try:
#         contents = [{"role": "user", "parts": [{"text": prompt}]}]
#         raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#         result = raw.strip().upper()
#         return result == "YES" or result.startswith("YES")
#     except Exception as e:
#         print(f"[DEBUG] Lỗi detect file query: {e}")
#         # Fallback an toàn: nếu lỗi → giả định là KHÔNG hỏi về file (để không bị lẫn RAG)
#         return False
    

# # ======================================================================
# # 5. GEMINI HISTORY + RAG + DB
# # ======================================================================
# def _to_gemini_history_no_system(history_msgs: List[Dict[str, str]]) -> List[Dict]:
#     out = []
#     for m in history_msgs:
#         role = m.get("role", "user")
#         content = (m.get("content") or "").strip()
#         if not content:
#             continue
#         role = "model" if role == "assistant" else "user"
#         out.append({"role": role, "parts": [{"text": content}]})
#     return out


# def _rewrite_db_answer(
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     answer_text: str,
#     lang_hint: str | None = None,
# ) -> str:
#     if not REWRITE_DB_WITH_LLM:
#         return answer_text

#     lang_hint = (lang_hint or "vi").lower()
#     if lang_hint.startswith("en"):
#         lang_rule = "\nTrả lời bằng tiếng Anh. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
#     else:
#         lang_rule = (
#             "\nTrả lời bằng tiếng Việt. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
#         )

#     guard = (
#         SYSTEM_PRIMER
#         + lang_rule
#         + "\nYÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô.\n"
#         "Không thêm bớt số. Nếu một số không cần thiết có quyền bỏ. "
#         "Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
#     )
#     contents = [
#         {
#             "role": "user",
#             "parts": [
#                 {
#                     "text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}",
#                 }
#             ],
#         }
#     ]
#     try:
#         out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#         out = strip_source_citations(out or "")
#         has_num_old = re.search(r"\d", answer_text or "") is not None
#         has_num_new = re.search(r"\d", out or "") is not None
#         if has_num_old and not has_num_new:
#             return answer_text
#         return out or answer_text
#     except Exception:
#         return answer_text


# # ======================================================================
# # SỬA LẠI _rag_answer – THÊM THAM SỐ only_use_session_docs
# # ======================================================================
# def _rag_answer(
#     user_text: str,
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     embeddings,
#     retriever,
#     lang_hint: str | None = None,
#     session_id: str | None = None,
#     session_doc_paths: Optional[List[str]] = None,
#     only_use_session_docs: bool = False,
# ) -> tuple[str, dict]:
#     session_doc_paths = session_doc_paths or []
#     # ← Đảm bảo không None
#     start_total = time.time()

#     session_docs: List[Document] = []
#     global_docs: List[Document] = []
#     search_time_session = 0.0
#     search_time_global = 0.0
#     rerank_time = 0.0

#     has_uploaded_files = bool(session_doc_paths)

#     # ==================================================================
#     # 1. TÌM TRONG FILE UPLOAD (dùng SUMMARY → siêu nhẹ, không load full nữa)
#     # ==================================================================
#     if has_uploaded_files:
#         try:
#             vs = _get_session_doc_vs(
#                 session_id=session_id,
#                 embeddings=embeddings,
#                 file_paths=session_doc_paths,
#                 gclient=gclient,
#                 GEMINI_MODEL=GEMINI_MODEL,
#                 GEN_CFG=GEN_CFG,
#             )
#             if vs is not None:
#                 t0 = time.time()
#                 session_docs = vs.similarity_search(user_text, k=20)
#                 search_time_session = time.time() - t0
#         except Exception as e:
#             print(f"[RAG] Lỗi khi tìm trong session docs: {e}")
#             session_docs = []

#     # ==================================================================
#     # 2. TÌM GLOBAL RAG (chỉ khi không bắt buộc chỉ dùng file)
#     # ==================================================================
#     if not only_use_session_docs:
#         try:
#             t0 = time.time()
#             global_docs = retriever.get_relevant_documents("query: " + user_text)
#             search_time_global = time.time() - t0
#         except Exception as e:
#             print(f"[RAG] Lỗi global RAG: {e}")

#     # ==================================================================
#     # 3. GỘP + RERANK
#     # ==================================================================
#     all_candidates = session_docs + global_docs

#     context_hint = ""
#     if not all_candidates:
#         if only_use_session_docs:
#             context_hint = "(Không tìm thấy thông tin phù hợp trong file bạn đã upload.)"
#         else:
#             context_hint = "(Không tìm thấy thông tin phù hợp từ tài liệu nội bộ.)"
#     else:
#         try:
#             t0 = time.time()
#             ranked = rerank(user_text, all_candidates, top_k=TOP_K)
#             rerank_time = time.time() - t0

#             parts = []
#             for doc, score in ranked:
#                 txt = doc.page_content
#                 if txt.lower().startswith("passage: "):
#                     txt = txt[len("passage: "):]

#                 meta = doc.metadata
#                 src_name = meta.get("source") or meta.get("title") or os.path.basename(meta.get("path", ""))
#                 is_summary = meta.get("is_summary", False)

#                 suffix = f" (Nguồn: {src_name}"
#                 if is_summary:
#                     suffix += " - Tóm tắt)"
#                 else:
#                     suffix += ")"

#                 parts.append(txt.strip() + suffix)

#             docs_text = "\n\n---\n\n".join(parts)
#             context_hint = f"Dữ liệu tham khảo:\n{docs_text}"
#         except Exception as e:
#             print(f"[RAG] Lỗi rerank: {e}")
#             context_hint = "(Có lỗi khi xử lý tài liệu tham khảo.)"

#     # ==================================================================
#     # 4. SYSTEM PROMPT + GỌI LLM
#     # ==================================================================
#     lang = (lang_hint or "vi").lower()
#     lang_instruction = "\nTrả lời bằng tiếng Anh, rõ ràng, chuyên nghiệp." if lang.startswith("en") else "\nTrả lời bằng tiếng Việt, tự nhiên, dễ hiểu."

#     system_prompt = f"""{SYSTEM_PRIMER}
# {lang_instruction}

# {context_hint}
# """

#     # Lấy history sạch
#     hist_msgs = [
#         m for m in get_history()
#         if m.get("role") in ("user", "assistant")
#     ]

#     contents = _to_gemini_history_no_system(hist_msgs)
#     contents.append({
#         "role": "user",
#         "parts": [{"text": f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_text}"}]
#     })

#     result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     final_answer = strip_source_citations(result.strip())

#     # ==================================================================
#     # 5. TIMING
#     # ==================================================================
#     timing = {
#         "embedding": 0.0,
#         "search": round(search_time_session + search_time_global + rerank_time, 2),
#         "llm": round(llm_time, 2),
#         "total": round(time.time() - start_total, 2),
#     }

#     return final_answer, timing

# # ======================================================================
# # 6. HÀM CHÍNH: xử lý 1 lượt chat (sync)
# # ======================================================================
# def handle_chat_request(
#     user_text: str,
#     session_id: str,
#     principal: Any,
#     bm25_folder: Optional[Path] = None,
#     corpus_path: Optional[Path] = None,
# ) -> dict:
#     user_text = (user_text or "").strip()
#     if not user_text:
#         return {"ok": False, "error": "Missing message"}

#     full_start = time.time()

#     # ====== Tạo session_id nếu chưa có ======
#     if not session_id:
#         try:
#             info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
#             session_id = info.get("session_id") or str(time.time())
#         except Exception:
#             session_id = str(time.time())

#     add_message("user", user_text, session_id=session_id)

#     # ====== Load LLM + RAG ======
#     bm25_folder = bm25_folder or DATA_DIR
#     corpus_path = corpus_path or (FAISS_ALL_DIR / "corpus.jsonl")

#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model(
#         bm25_folder=bm25_folder,
#         corpus_path=corpus_path,
#     )

#     # ====== Load context & history ======
#     ctx = _load_ctx(session_id)
#     history_msgs = _get_history_msgs_for_ctx()

#     # ====== 1. Xử lý dịch / viết lại ======
#     analysis = _analyze_followup_and_lang(
#         gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
#     )

#     if analysis.get("mode") == "edit":
#         final_answer = strip_source_citations(analysis.get("output", ""))
#         add_message("assistant", final_answer, session_id=session_id)
#         ctx["lang"] = analysis.get("set_lang") or ctx.get("lang", "vi")
#         ctx["last_branch"] = "editor"
#         update_ctx(session_id, ctx)
#         return {
#             "ok": True,
#             "answer": final_answer,
#             "session_id": session_id,
#             "branch": "editor",
#             "timing": {"total": round(time.time() - full_start, 2)},
#         }

#     # ====== 2. Xử lý lệnh xoá file ======
#     if user_text.lower().strip() in ["xóa file", "xoá file", "hủy file", "delete file", "clear file"]:
#         session.pop("uploaded_files", None)
#         _clear_session_doc_vs(session_id)
#         final_answer = "Đã xoá toàn bộ file đã upload trong phiên này."
#         add_message("assistant", final_answer, session_id=session_id)
#         return {
#             "ok": True,
#             "answer": final_answer,
#             "session_id": session_id,
#             "branch": "doc_clear",
#             "timing": {"total": round(time.time() - full_start, 2)},
#         }

#     # ====== 3. Lấy file upload ======
#     uploaded_files_meta = session.get("uploaded_files", [])
#     session_doc_paths: List[str] = [
#         item["path"] for item in uploaded_files_meta
#         if isinstance(item, dict) and item.get("path") and os.path.exists(item["path"])
#     ]

#     # ====== 4. Cập nhật ngôn ngữ ======
#     if analysis.get("set_lang") in ("vi", "en"):
#         ctx["lang"] = analysis.get("set_lang")
#     elif "lang" not in ctx:
#         ctx["lang"] = _auto_detect_lang(user_text)

#     # ====== 5. Kiểm tra DB trước ======
#     handled, db_answer, meta = handle_db_message(user_text, session_id, principal=principal)

#     if handled:
#         final_answer = _rewrite_db_answer(
#             gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang")
#         )
#         ctx["last_branch"] = "db"
#     else:
#         # ====== 6. RAG – QUYẾT ĐỊNH CHỈ DÙNG FILE HAY CẢ GLOBAL ======
#         only_use_session_docs = False
#         if session_doc_paths:
#             only_use_session_docs = _is_query_about_uploaded_file(
#                 user_text=user_text,
#                 lang=ctx.get("lang", "vi"),
#                 gclient=gclient,
#                 GEMINI_MODEL=GEMINI_MODEL,
#                 GEN_CFG=GEN_CFG,
#             )
#             print(f"[FILE DETECT] only_use_session_docs = {only_use_session_docs} | query: '{user_text}'")

#         final_answer, timing = _rag_answer(
#             user_text=user_text,
#             gclient=gclient,
#             GEMINI_MODEL=GEMINI_MODEL,
#             GEN_CFG=GEN_CFG,
#             embeddings=embeddings,
#             retriever=retriever,
#             lang_hint=ctx.get("lang"),
#             session_id=session_id,
#             session_doc_paths=session_doc_paths,
#             only_use_session_docs=only_use_session_docs,
#         )

#         ctx["last_branch"] = "rag_file_only" if only_use_session_docs else "rag"
#         if session_doc_paths:
#             ctx["last_docs"] = [os.path.basename(p) for p in session_doc_paths]

#     # ====== Ghi trả lời ======
#     add_message("assistant", final_answer, session_id=session_id)

#     # ====== Cập nhật context ======
#     try:
#         update_ctx(session_id, ctx)
#     except Exception:
#         pass

#     # ====== Smart Summary (giữ nguyên nếu bạn có) ======
#     try:
#         history = get_history()
#         user_count = len([m for m in history if m.get("role") == "user"])
#         if user_count >= 7 and user_count % 7 == 0:
#             # (giữ nguyên phần summary cũ nếu cần)
#             pass
#     except Exception:
#         pass

#     elapsed = time.time() - full_start
#     return {
#         "ok": True,
#         "answer": final_answer,
#         "session_id": session_id,
#         "branch": ctx.get("last_branch", "rag"),
#         "meta": meta or {},
#         "timing": {
#             "total": round(elapsed, 2),
#             **(timing if 'timing' in locals() else {}),
#         },
#     }





from __future__ import annotations

import os
import re
import time
import json
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import fitz
import docx as docx_lib
from flask import session
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from app.services.history import get_history, add_message, create_new_session
from app.Helpers.prompt_internal import SYSTEM_PRIMER, sys_instr
from app.Model_LLM.model_llm import LLM_model
from app.Model_LLM.hybrid_retriever import rerank, TOP_K
from app.config.settings import ChatConfig, Chat_engine
from app.Model_LLM.Chat_Database.db_router import handle_db_message
from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx, redis_client
from app.config.paths import DATA_DIR, FAISS_ALL_DIR

# OCR cho ảnh
from .image_ocr_utils import (
    extract_text_from_image,
    is_image_path,
)

LLM_SEM = ChatConfig.LLM_SEM
DB_CONF_THRESHOLD = Chat_engine.DB_CONF_THRESHOLD
REWRITE_DB_WITH_LLM = Chat_engine.REWRITE_DB_WITH_LLM

# Mini FAISS cache cho tài liệu upload theo session (trong memory)
SESSION_DOC_VS: Dict[str, FAISS] = {}
SESSION_DOC_VS_META: Dict[str, Dict[str, float]] = {}
SESSION_DOC_SUMMARY: Dict[str, str] = {}


# ======================================================================
# 0. DETECT FILE FOCUS / CÂU "FILE NÀY" (prompt-based)
# ======================================================================
def _detect_focus_sources_from_query(
    user_text: str,
    uploaded_files_meta: List[Dict[str, Any]],
) -> Optional[List[str]]:
    """
    Tìm xem câu hỏi đang nhắc tới file nào (hoặc nhiều file nào) theo TÊN.

    - User có thể gõ: 
      + đúng tên: "vi-du-phieu-chi.jpg"
      + gần đúng: "vi du phieu chi", "vi_du_phieu_chi"
      + thiếu bớt đuôi: "vi-du-phieu-chi"
    - So khớp tolerant:
      + bỏ dấu tiếng Việt
      + coi "_", "-", "." như khoảng trắng
    - Trả về danh sách basename (stored_name) để khớp với metadata["source"].
    Nếu không match được file nào thì trả về None (nghĩa là dùng tất cả file).
    """
    if not user_text or not uploaded_files_meta:
        return None

    # Chuẩn hoá câu hỏi
    q_norm = _normalize_for_filename_match(user_text)

    matched_sources: List[str] = []

    for item in uploaded_files_meta:
        if not isinstance(item, dict):
            continue

        raw_name = (item.get("name") or "")
        stored   = (item.get("stored_name") or "")
        path     = (item.get("path") or "")

        basename = os.path.basename(path or stored or raw_name)
        basename_lower = basename.lower()

        # Các candidate gốc (chưa normalize)
        candidates_raw = [
            raw_name,
            stored,
            os.path.splitext(raw_name)[0],
            os.path.splitext(basename_lower)[0],
        ]

        # Chuẩn hoá từng candidate để so với q_norm
        found = False
        for c in candidates_raw:
            if not c:
                continue
            c_norm = _normalize_for_filename_match(c)

            # Nếu chuỗi rỗng sau normalize thì bỏ
            if not c_norm:
                continue

            # Ví dụ:
            #   c_norm = "khai thac du lieu va ung dung du oan benh tim mach"
            #   q_norm = "khai thac du lieu va ung dung du oan benh tim mach pdf noi dung 2 file tren"
            if c_norm in q_norm:
                if basename not in matched_sources:
                    matched_sources.append(basename)
                found = True
                break

        # Nếu chưa match theo full tên, thử match theo "core name" rút gọn:
        if not found:
            core = os.path.splitext(basename_lower)[0]
            core_norm = _normalize_for_filename_match(core)

            # Nếu core_norm dài đủ (tránh các tên quá ngắn kiểu "cv" / "a")
            if core_norm and len(core_norm) >= 6 and core_norm in q_norm:
                if basename not in matched_sources:
                    matched_sources.append(basename)

    if not matched_sources:
        return None
    return matched_sources



def _get_latest_batch_paths(flat_metas: List[Dict[str, Any]]) -> List[str]:
    """
    Dựa vào stored_name = "<timestamp>_xxx.ext" để suy ra batch upload mới nhất.
    Trả về list path của batch mới nhất (không trùng, có tồn tại trên disk).
    """
    if not flat_metas:
        return []

    batches: Dict[str, List[Dict[str, Any]]] = {}

    for m in flat_metas:
        if not isinstance(m, dict):
            continue
        stored = str(m.get("stored_name") or "")
        path = m.get("path")

        if not path:
            continue

        # tách prefix trước "_" làm batch_id
        batch_id = ""
        if "_" in stored:
            batch_id = stored.split("_", 1)[0]
        else:
            batch_id = "legacy"

        batches.setdefault(batch_id, []).append(m)

    if not batches:
        return []

    # ưu tiên batch_id là số (timestamp), chọn lớn nhất
    numeric_ids = [bid for bid in batches.keys() if bid.isdigit()]
    if numeric_ids:
        latest_id = max(numeric_ids, key=int)
        latest_metas = batches[latest_id]
    else:
        # fallback: nếu không có numeric id → lấy nhóm "legacy" hoặc tất cả
        latest_metas = batches.get("legacy", flat_metas[-3:])

    paths: List[str] = []
    seen: set[str] = set()
    for m in latest_metas:
        p = m.get("path")
        if p and isinstance(p, str) and os.path.exists(p) and p not in seen:
            paths.append(p)
            seen.add(p)

    return paths

def _is_generic_current_file_query(
    user_text: str,
    gclient=None,
    GEMINI_MODEL=None,
    GEN_CFG=None,
) -> bool:
    """
    Dùng Gemini để detect các câu kiểu:
    - "file này", "file trên", "file vừa rồi"
    - "hóa đơn này", "ảnh trên", "2 file này", "các file này", "những file trên"
    => user đang nói chung chung về file hiện tại / các file vừa upload,
    KHÔNG nêu tên file cụ thể.
    """
    if not gclient or not user_text.strip():
        return False

    query = user_text.strip()[:1500]

    prompt = f"""Bạn là chuyên gia phân tích ngữ cảnh chat với trợ lý ảo có chức năng đọc file người dùng đã upload.

NHIỆM VỤ:
Quyết định xem câu hỏi của người dùng có phải kiểu nói CHUNG CHUNG về "file hiện tại" hoặc "những file vừa upload" hay không.

ĐỊNH NGHĨA "CÂU HỎI CHUNG CHUNG VỀ FILE HIỆN TẠI":
- User dùng các cụm như:
  + "file này", "file trên", "file vừa rồi", "file mới up", "file hiện tại"
  + hoặc "hóa đơn này", "hóa đơn trên", "ảnh này", "hình trên"
  + hoặc "2 file này", "3 file này", "các file này", "các file trên", "những file này", "những file trên"
- KHÔNG nêu tên file cụ thể (không nói rõ như "file CV_PhanDuyBao_AIEngineer.pdf").

VÍ DỤ → YES:
- "file này là gì?"
- "tóm tắt nội dung file trên"
- "2 file này khác nhau gì?"
- "ảnh trên là hóa đơn gì?"
- "hóa đơn này tổng tiền bao nhiêu?"
- "so sánh nội dung 2 file này giúp tôi"

VÍ DỤ → NO:
- "tóm tắt quy định nghỉ phép của công ty"
- "cho tôi quy trình nhập kho"
- "tổng hợp nội dung file BáoCaoThucTap.docx"
- "tóm tắt nội dung file CV_PhanDuyBao_AIEngineer.pdf"
- "cho tôi những tài liệu liên quan về công ty"

Câu hỏi người dùng:
{query}

Nếu câu hỏi thuộc loại "chung chung về file hiện tại" như định nghĩa ở trên,
hãy trả lời đúng 1 từ: YES
Nếu không, trả lời đúng 1 từ: NO
Không giải thích thêm.
Trả lời:
"""

    try:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        result = (raw or "").strip().upper()
        return result == "YES" or result.startswith("YES")
    except Exception as e:
        print(f"[DEBUG] Lỗi detect generic current file query: {e}")
        # fallback an toàn
        return False


# ======================================================================
# 1. HISTORY / CTX HELPERS
# ======================================================================
def _normalize_vi(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def _get_history_msgs_for_ctx() -> List[Dict[str, str]]:
    try:
        hist = [
            {"role": m["role"], "content": m["content"]}
            for m in get_history()
            if m["role"] in ("user", "assistant")
        ]
    except Exception:
        hist = []
    return hist


def _get_last_assistant_message(history_msgs: List[Dict[str, str]]) -> Optional[str]:
    for m in reversed(history_msgs or []):
        if m.get("role") == "assistant":
            content = (m.get("content") or "").strip()
            if content:
                return content
    return None


def _load_ctx(session_id: str) -> Dict[str, Any]:
    try:
        ctx = get_ctx(session_id) or {}
        if not isinstance(ctx, dict):
            return {}
        return ctx
    except Exception:
        return {}


# ======================================================================
# 2. DETECT NGÔN NGỮ ĐƠN GIẢN
# ======================================================================
def _auto_detect_lang(text: str) -> str:
    text = text or ""
    vi_chars = re.findall(
        r"[àáạảãăằắặẳẵâầấậẩẫèéẹẻẽêềếệểễ"
        r"ìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũư"
        r"ừứựửữỳýỵỷỹđÀÁẠẢÃĂẰẮẶẲẴÂẦẤẬẨẪ"
        r"ÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠ"
        r"ỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]",
        text,
    )
    if len(vi_chars) >= 1:
        return "vi"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "vi"


def _make_summary_key(session_id: str, path: str) -> str:
    basename = os.path.basename(path)
    try:
        mtime = int(os.path.getmtime(path))
    except Exception:
        mtime = 0
    return f"file_summary:{session_id}:{basename}:{mtime}"


# ======================================================================
# 3. EDITOR: DỊCH/VIẾT LẠI CÂU TRẢ LỜI TRƯỚC
# ======================================================================
def _contents_to_ollama_messages(contents):
    msgs = []
    for m in contents or []:
        role = m.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        text_parts = []
        for p in m.get("parts") or []:
            if isinstance(p, dict) and p.get("text"):
                text_parts.append(p["text"])
        if not text_parts:
            continue
        msgs.append({"role": role, "content": "\n".join(text_parts)})
    return msgs


def _estimate_from_contents(contents, max_out_tokens=1024) -> int:
    words = 0
    for m in contents or []:
        for p in (m.get("parts") or []):
            if isinstance(p, dict) and p.get("text"):
                words += len(p["text"].split())
    return int(1.3 * words) + int(max_out_tokens or 512)


def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
    from app.Helpers.rate_limit import get_text_limiter

    limiter = get_text_limiter()
    max_out = (
        config.get("max_output_tokens")
        if isinstance(config, dict)
        else getattr(config, "max_output_tokens", 1024)
    )
    tokens_est = _estimate_from_contents(contents, max_out)
    last_err: Optional[Exception] = None

    for i in range(retries + 1):
        try:
            limiter.acquire(tokens_est)
            t0 = time.time()
            with LLM_SEM:
                resp = gclient.models.generate_content(
                    model=model, contents=contents, config=config
                )
            limiter.on_success()
            return (getattr(resp, "text", "") or ""), time.time() - t0
        except Exception as e:
            last_err = e
            s = str(e).lower()
            if ("429" in s or "quota" in s or "resource_exhausted" in s) and i < retries:
                limiter.on_429()
                time.sleep(backoff * (2 ** i))
                continue
            limiter.on_429()
            raise last_err


def _rewrite_last_answer_for_lang(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    last_answer: str,
    target_lang: str = "en",
) -> str:
    last_answer = (last_answer or "").strip()
    if not last_answer:
        return ""
    target_lang = (target_lang or "en").lower()

    if target_lang.startswith("en"):
        instr = (
            "Rewrite the following answer in clear, natural English. "
            "Keep the meaning and important details, but you can shorten slightly if needed.\n"
            "Answer ONLY in English.\n"
        )
    else:
        instr = (
            "Viết lại câu trả lời sau bằng tiếng Việt rõ ràng, tự nhiên. "
            "Giữ nguyên ý chính và các chi tiết quan trọng, có thể rút gọn nhẹ nếu cần.\n"
            "Chỉ trả lời bằng tiếng Việt.\n"
        )

    prompt = f"""{instr}
    [ANSWER]
    {last_answer}
    """
    contents = [
        {
            "role": "user",
            "parts": [{"text": prompt}],
        }
    ]
    out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    return (out or "").strip()


def _analyze_followup_and_lang(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    user_text: str,
    history_msgs: List[Dict[str, str]],
    ctx: Dict[str, Any],
):
    user_text = (user_text or "").strip()
    if not user_text:
        return {"mode": "pass", "output": "", "set_lang": None}

    last_ans = _get_last_assistant_message(history_msgs)
    if not last_ans:
        return {"mode": "pass", "output": "", "set_lang": None}

    current_lang = (ctx or {}).get("lang") or "vi"
    lower_ut = user_text.lower()

    vi_to_en_patterns = [
        "viết bằng tiếng anh",
        "viết lại bằng tiếng anh",
        "viết tiếng anh",
        "dịch sang tiếng anh",
        "dịch đoạn trên sang tiếng anh",
        "dịch nội dung trên sang tiếng anh",
        "rewrite in english",
        "write in english",
        "answer in english",
        "translate to english",
    ]
    en_to_vi_patterns = [
        "viết bằng tiếng việt",
        "viết lại bằng tiếng việt",
        "dịch sang tiếng việt",
        "dịch đoạn trên sang tiếng việt",
        "dịch nội dung trên sang tiếng việt",
        "rewrite in vietnamese",
        "translate to vietnamese",
    ]

    if any(p in lower_ut for p in vi_to_en_patterns):
        out_text = _rewrite_last_answer_for_lang(
            gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="en"
        )
        return {
            "mode": "edit",
            "output": out_text,
            "set_lang": "en",
        }

    if any(p in lower_ut for p in en_to_vi_patterns):
        out_text = _rewrite_last_answer_for_lang(
            gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="vi"
        )
        return {
            "mode": "edit",
            "output": out_text,
            "set_lang": "vi",
        }

    prompt = f"""{sys_instr}
    [CURRENT_PREFERRED_LANG]
    {current_lang}
    [PREVIOUS_ANSWER]
    {last_ans}
    [USER_REQUEST]
    {user_text}
    """
    contents = [
        {
            "role": "user",
            "parts": [{"text": prompt}],
        }
    ]
    raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    raw = (raw or "").strip()

    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    mode = (data.get("mode") or "pass").lower()
    output = (data.get("output") or "").strip()
    set_lang = data.get("set_lang", None)

    if set_lang is not None:
        if isinstance(set_lang, str):
            set_lang = set_lang.lower()
            if set_lang not in ("vi", "en"):
                set_lang = None
        else:
            set_lang = None

    if set_lang is None:
        detected = _auto_detect_lang(user_text)
        if detected in ("vi", "en") and detected != current_lang:
            set_lang = detected

    if mode != "edit" or not output:
        return {"mode": "pass", "output": "", "set_lang": set_lang}

    return {"mode": "edit", "output": output, "set_lang": set_lang}


# ======================================================================
# 4. FILE UPLOAD (VS session) + STRIP SOURCE
# ======================================================================
def strip_source_citations(text: str) -> str:
    if not text:
        return text

    text = re.sub(
        r'\s*\(?\s*[Nn]gu[oơ]n\s*:\s*[^\n\)]*\.(?:txt|docx|pdf)\s*\)?',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r'\bsource["\']?\s*:\s*["\']?[^"\n]*\.(?:txt|docx|pdf)["\']?',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'[\(\[\{]\s*(?:source|chunk_id|metadata|norm_case|Nguồn)[\s:][^\)\]\}]{0,400}[\)\]\}]',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'\(\s*[Ll]ink\s*:\s*(?!https?://)[^)]*\.(?:txt|docx|pdf)\s*\)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\b[Ll]ink\s*:\s*(?!https?://)[^\n]*\.(?:txt|docx|pdf)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\b[Nn]gu[oơ]n\s*:\s*[^\n]*\.(?:txt|docx|pdf)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\(Accountant\\[^\)]*\.(?:txt|docx|pdf)\)',
        '',
        text,
        flags=re.DOTALL,
    )

    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\.{3,}', '...', text)
    text = text.strip()
    return text

def _normalize_simple(text: str) -> str:
    """
    Chuẩn hóa đơn giản: bỏ dấu + lower → dùng để detect prompt nội bộ,
    tránh phụ thuộc vào dấu tiếng Việt.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()

def _normalize_for_filename_match(text: str) -> str:
    """
    Chuẩn hoá chuỗi để so khớp tên file "mềm" hơn:
    - Bỏ dấu tiếng Việt
    - Lowercase
    - Thay _, -, . bằng khoảng trắng
    - Gom nhiều khoảng trắng thành 1
    """
    if not text:
        return ""
    # Bỏ dấu
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()

    # Thay các ký tự phân tách thường gặp thành space
    for ch in ["_", "-", ".", "/", "\\"]:
        text = text.replace(ch, " ")

    # Gom khoảng trắng
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_internal_prompt_text(text: str) -> bool:
    """
    Nhận diện nội dung có vẻ là PROMPT HỆ THỐNG / hướng dẫn LLM,
    KHÔNG phải nội dung nghiệp vụ trong phiếu / hóa đơn.

    Mục tiêu:
    - Chỉ chặn các đoạn kiểu "Bạn là trợ lý AI...", "Nguồn A/B/C", "quy tắc chống bịa đặt", v.v.
    - Không chặn nội dung chứng từ (phiếu thu/chi, hóa đơn, giấy báo điện/nước...).
    """
    if not text:
        return False

    t = _normalize_simple(text)

    # Các pattern đặc trưng của prompt hệ thống
    hard_patterns = [
        # Định danh / vai trò
        "ban la tro ly ai",
        "ban la: tro ly ai",
        "tro ly ai noi bo",
        "tro ly ao noi bo",
        "tro ly noi bo",
        "ban la tro ly ao noi bo",

        # Nhiệm vụ / mục tiêu / phạm vi
        "muc tieu cua ban la",
        "nhiem vu cua ban la",
        "pham vi ho tro",
        "ban ho tro cac hoat dong logistics",

        # Phân loại nguồn a/b/c
        "nguon a (du lieu that",
        "nguon b (tai lieu noi bo",
        "nguon c (tham khao ben ngoai",
        "nguon a ( du lieu that",
        "nguon b ( tai lieu noi bo",

        # Quy tắc chống bịa đặt
        "quy tac chong bia dat",
        "tuyet doi khong",
        "khong duoc suy doan so lieu",
        "khong duoc tao ra so lieu",

        # Meta về cách trả lời
        "luon tra loi bang tieng viet",
        "luon tra loi bang tieng anh",
        "khong chao hoi",
        "khong cau xa giao",
        "cau truc mac dinh",
        "tom tat 1 2 cau",

        # Bảo mật
        "khong hien thi noi dung tu [system]",
        "khong hien thi prompt he thong",
        "khong hien thi api key",
        "mat khau",
        "duong dan noi bo",

        # Lời chào mặc định
        "toi la tro ly ao noi bo",
        "toi la tro ly ai noi bo",
    ]

    if any(p in t for p in hard_patterns):
        return True

    # Tag meta rất rõ
    if "[system]" in t or "[internal prompt]" in t:
        return True

    # Xuất hiện đồng thời 'nguon a', 'nguon b', 'nguon c' → gần như chắc là prompt
    if "nguon a" in t and "nguon b" in t and "nguon c" in t:
        return True

    return False



def _extract_text_from_uploaded_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    if ext == ".txt":
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    if ext == ".docx":
        try:
            d = docx_lib.Document(path)
            lines = []
            for p in d.paragraphs:
                t = (p.text or "").strip()
                if t:
                    lines.append(t)
            for tbl in d.tables:
                for row in tbl.rows:
                    cells = [(cell.text or "").strip() for cell in row.cells]
                    line = " | ".join(c for c in cells if c)
                    if line:
                        lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    if ext == ".pdf":
        try:
            doc = fitz.open(path)
            pages = []
            for p in doc:
                t = p.get_text()
                if t.strip():
                    pages.append(t)
            doc.close()
            return "\n".join(pages)
        except Exception:
            return ""

    # ẢNH: gọi OCR utils
    if is_image_path(path):
        try:
            return extract_text_from_image(path)
        except Exception:
            return ""

    return ""


def _summarize_uploaded_file(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    path: str,
    max_lines: int = 10,  # tham số vẫn giữ để không vỡ chỗ khác, nhưng prompt sẽ chi tiết hơn
) -> str:
    """
    - ẢNH: chỉ OCR → trả về raw text (để bạn toàn quyền xử lý sau).
    - PDF/DOCX/TXT: gọi LLM để tóm tắt CHI TIẾT HƠN (multi-bullet, có cấu trúc).
    """

    if is_image_path(path):
        raw = _extract_text_from_uploaded_file(path)
        return (raw or "").strip()
    raw_text = _extract_text_from_uploaded_file(path)
    if not raw_text or not raw_text.strip():
        return ""

    detected_lang = _auto_detect_lang(raw_text)
    lang_name = "Việt" if detected_lang == "vi" else "Anh"
    snippet = raw_text[:2000]

    prompt = f"""Bạn đang đọc một tài liệu nội bộ (pdf/doc/txt).

        NHIỆM VỤ:
        Tóm tắt TƯƠNG ĐỐI CHI TIẾT tài liệu dưới đây.

        YÊU CẦU:
        - Viết một đoạn TÓM TẮT NGẮN 1–2 câu ở đầu.
        - Sau đó viết 5–12 gạch đầu dòng mô tả chi tiết:
        + Mục tiêu / chủ đề chính của tài liệu.
        + Đối tượng, bối cảnh (nếu nhận diện được).
        + Cấu trúc các chương / mục chính (liệt kê tên chương hoặc chủ đề).
        + Phương pháp / kỹ thuật / nội dung quan trọng.
        + Kết quả, kết luận hoặc kiến nghị chính.
        + Ứng dụng hoặc ý nghĩa thực tiễn (nếu có).
        - BÁM SÁT nội dung thực tế trong tài liệu, không nói chung chung.
        - Nếu tài liệu là khóa luận / luận văn:
        + Ghi rõ tên đề tài (title), tên tác giả, loại luận văn (khóa luận tốt nghiệp, luận văn thạc sĩ...).
        + Tóm tắt ngắn gọn nội dung các chương chính (Chương 1, Chương 2...).
        - Nếu tài liệu là slide / ebook về AI:
        + Liệt kê các khái niệm, kỹ thuật, hoặc chương quan trọng (ví dụ: khái niệm AI, Machine Learning, Deep Learning, ứng dụng AI trong doanh nghiệp...).
        - Không cần nhắc lại đường dẫn file, chỉ tập trung vào nội dung.
        - Trả lời bằng tiếng {lang_name}.

        [TÀI LIỆU]
        {snippet}
        """

    contents = [{"role": "user", "parts": [{"text": prompt}]}]

    try:
        summary, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        summary = (summary or "").strip()

        # Nếu LLM trả lời quá ngắn (ví dụ < 200 ký tự) → fallback một phần raw_text
        if len(summary) < 200:
            fallback = raw_text[:2000].strip()
            return summary + "\n\n" + fallback if summary else fallback

        return summary
    except Exception:
        # Lỗi LLM → fallback raw text rút gọn
        return raw_text[:2000].strip()





def _split_text_to_chunks(text: str, max_chars: int = 800, overlap: int = 200) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks


def _build_session_doc_vs(
    session_id: str,
    embeddings,
    file_paths: List[str],
    file_meta_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[FAISS]:
    """
    Build VS từ FULL TEXT (ít dùng khi đã có summary),
    nhưng vẫn giữ để fallback. Có thêm file_type / is_image trong meta.
    """
    file_meta_map = file_meta_map or {}

    if not session_id or not file_paths:
        return None

    texts: List[str] = []
    metas: List[Dict[str, Any]] = []

    for path in file_paths:
        if not path or not os.path.exists(path):
            continue
        try:
            raw = _extract_text_from_uploaded_file(path)
        except Exception:
            raw = ""
        if not raw.strip():
            continue

        chunks = _split_text_to_chunks(raw, max_chars=800, overlap=200)
        src = os.path.basename(path)

        meta_for_file = file_meta_map.get(path, {})
        file_type = meta_for_file.get("file_type")
        if not file_type:
            file_type = "image" if is_image_path(path) else "doc"

        for ch in chunks:
            texts.append(ch)
            metas.append({
                "source": src,
                "session_id": session_id,
                "is_summary": False,
                "file_type": file_type,
                "is_image": file_type == "image",
            })

    if not texts:
        return None

    vs = FAISS.from_texts(texts, embeddings, metadatas=metas)

    SESSION_DOC_VS[session_id] = vs
    meta_map: Dict[str, float] = {}
    for p in file_paths:
        if p and os.path.exists(p):
            meta_map[p] = os.path.getmtime(p)
    SESSION_DOC_VS_META[session_id] = meta_map
    return vs

def _filter_internal_prompt_docs(docs: List[Document]) -> List[Document]:
    """
    Loại bỏ các Document mà nội dung là prompt hệ thống / hướng dẫn LLM,
    để model không trả lời kiểu 'Hình 1 là Prompt Hệ Thống...'
    """
    cleaned: List[Document] = []
    for d in docs or []:
        txt = (d.page_content or "").strip()
        if not txt:
            continue
        if _is_internal_prompt_text(txt):
            continue
        cleaned.append(d)
    return cleaned


# ======================================================================
# _get_session_doc_vs – dùng SUMMARY + Redis key theo mtime
# ======================================================================

def _get_session_doc_vs(
    session_id: str,
    embeddings,
    file_paths: List[str],
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    file_meta_map: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[FAISS]:
    """
    Xây / lấy lại FAISS vectorstore cho các file đã upload trong 1 session.
    - ẢNH: OCR → tóm tắt → chunk → FAISS
    - PDF/DOCX/TXT: đọc text → tóm tắt → chunk → FAISS
    - Dùng meta (path → mtime) để quyết định có reuse VS hay không.
    - Nếu meta đổi → xóa VS cũ + meta cũ + toàn bộ summary cũ của session.
    - Summary được cache riêng theo (session, basename, mtime).
    """
    if not session_id or not file_paths:
        return None

    # 1. meta hiện tại (dùng mtime, không phụ thuộc file_meta_map cũ)
    current_meta: Dict[str, float] = {}
    for p in file_paths:
        if os.path.exists(p):
            try:
                current_meta[p] = os.path.getmtime(p)
            except Exception:
                continue

    if not current_meta:
        SESSION_DOC_VS.pop(session_id, None)
        SESSION_DOC_VS_META.pop(session_id, None)
        try:
            redis_client.delete(f"session_doc_vs_meta:{session_id}")
            keys = redis_client.keys(f"file_summary:{session_id}:*")
            if keys:
                redis_client.delete(*keys)
        except Exception:
            pass
        return None

    # 2. đọc meta cache trong Redis
    cached_meta_key = f"session_doc_vs_meta:{session_id}"
    cached_meta_str = redis_client.get(cached_meta_key)  # None hoặc str JSON
    cached_meta: Dict[str, float] = {}
    if cached_meta_str:
        try:
            cached_meta = json.loads(cached_meta_str)
        except json.JSONDecodeError:
            cached_meta = {}

    # 3. nếu meta giống → dùng lại VS
    same_meta = bool(cached_meta) and (cached_meta == current_meta)
    if same_meta and session_id in SESSION_DOC_VS:
        return SESSION_DOC_VS[session_id]

    # 4. meta khác → invalidate cache cũ
    if not same_meta:
        SESSION_DOC_VS.pop(session_id, None)
        SESSION_DOC_VS_META.pop(session_id, None)
        try:
            redis_client.delete(cached_meta_key)
        except Exception:
            pass
        try:
            keys = redis_client.keys(f"file_summary:{session_id}:*")
            if keys:
                redis_client.delete(*keys)
        except Exception:
            pass

    # 5. Build VS mới từ SUMMARY (DOC + ẢNH)
    texts: List[str] = []
    metas: List[Dict[str, Any]] = []

    for path in file_paths:
        if not os.path.exists(path):
            continue

        summary_key = _make_summary_key(session_id, path)
        summary_raw = redis_client.get(summary_key)

        summary: Optional[str] = None
        if summary_raw is not None:
            if isinstance(summary_raw, bytes):
                try:
                    summary = summary_raw.decode("utf-8")
                except Exception:
                    summary = None
            elif isinstance(summary_raw, str):
                summary = summary_raw
            else:
                summary = str(summary_raw)

        # Nếu cache cũ nhưng là prompt hệ thống → coi như không hợp lệ
        if summary and _is_internal_prompt_text(summary):
            summary = None

        if not summary or not str(summary).strip():
            summary = _summarize_uploaded_file(
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
                path=path,
            )
            # CHỈ cache nếu không phải prompt
            if summary and summary.strip() and not _is_internal_prompt_text(summary):
                try:
                    redis_client.set(summary_key, summary, ex=86400)
                except Exception:
                    pass

        if not summary or not str(summary).strip():
            continue


        # ẢNH hay PDF/DOCX/TXT đều đã được gom thành summary ở trên
        chunks = _split_text_to_chunks(str(summary), max_chars=500, overlap=100)
        src = os.path.basename(path)
        for ch in chunks:
            texts.append(ch)
            metas.append(
                {
                    "source": src,
                    "session_id": session_id,
                    "is_summary": True,
                }
            )

    if not texts:
        SESSION_DOC_VS.pop(session_id, None)
        SESSION_DOC_VS_META.pop(session_id, None)
        try:
            redis_client.delete(cached_meta_key)
        except Exception:
            pass
        return None

    vs = FAISS.from_texts(texts, embeddings, metadatas=metas)
    SESSION_DOC_VS[session_id] = vs
    SESSION_DOC_VS_META[session_id] = current_meta

    try:
        meta_json = json.dumps(current_meta)
        redis_client.set(cached_meta_key, meta_json, ex=86400)
    except Exception:
        pass

    return vs

def _clear_session_doc_vs(session_id: str) -> None:
    SESSION_DOC_VS.pop(session_id, None)
    SESSION_DOC_VS_META.pop(session_id, None)

    redis_client.delete(f"session_doc_vs_meta:{session_id}")
    keys = redis_client.keys(f"file_summary:{session_id}:*")
    if keys:
        redis_client.delete(*keys)


def _filter_internal_prompt_docs(docs: List[Document]) -> List[Document]:
    """
    Loại bỏ các Document mà nội dung là prompt hệ thống / hướng dẫn LLM,
    để model không trả lời kiểu 'Hình 1 là Prompt Hệ Thống...'
    """
    cleaned: List[Document] = []
    for d in docs or []:
        txt = (d.page_content or "").strip()
        if not txt:
            continue
        if _is_internal_prompt_text(txt):
            continue
        cleaned.append(d)
    return cleaned


def _extract_src_and_url(meta: dict) -> tuple[str, str]:
    if not isinstance(meta, dict):
        return "", ""
    src_name = (
        meta.get("title")
        or meta.get("source")
        or meta.get("filename")
        or ""
    )
    url = meta.get("url") or meta.get("link") or meta.get("path") or ""
    if "http" not in url and (src_name.endswith(('.txt', '.docx', '.pdf')) or '\\' in src_name):
        src_name = ""
    return src_name or "", url or ""


def _is_query_about_uploaded_file(
    user_text: str,
    lang: str = "vi",
    gclient=None,
    GEMINI_MODEL=None,
    GEN_CFG=None,
) -> bool:
    """
    Dùng Gemini để quyết định: người dùng có đang hỏi về file đã upload không?
    Trả lời YES/NO, không dùng pattern cứng.
    """
    if not gclient or not user_text.strip():
        return False

    query = user_text.strip()[:15000]
    prompt = f"""Bạn là chuyên gia phân tích ngữ cảnh chat.
    Có file đã được upload trong phiên này.
    Người dùng có đang hỏi cụ thể về nội dung của file đó không?
    Chỉ trả lời đúng 1 từ: YES hoặc NO. Không giải thích.
    Ví dụ:
    - "tóm tắt" → YES
    - "nội dung file trên" → YES
    - "cái này nói gì" → YES
    - "file này là gì" → YES
    - "quy trình nghỉ phép mới nhất?" → NO
    - "lương tháng này bao nhiêu?" → NO
    Câu hỏi người dùng: {query}
    Trả lời:"""
    try:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        result = (raw or "").strip().upper()
        return result == "YES" or result.startswith("YES")
    except Exception as e:
        print(f"[DEBUG] Lỗi detect file query: {e}")
        return False

def _is_request_uploaded_files_content(text: str) -> bool:
    """
    Nhận diện các câu kiểu:
    - "nội dung các file trên"
    - "tôi muốn biết nội dung 2 file này"
    - "nội dung mấy file vừa up"
    Mục tiêu: user muốn biết nội dung từng file, không phải hỏi quy trình hay hỏi DB.
    """
    if not text:
        return False

    t = _normalize_vi(text.lower())

    # Phải có "nội dung"
    if "noi dung" not in t:
        return False

    # Và có từ chỉ file / hình / tài liệu
    if (
        "file" in t
        or "tai lieu" in t
        or "hinh" in t
        or "anh" in t
        or "hoa don" in t
    ):
        return True

    return False

# ======================================================================
# 5. GEMINI HISTORY + RAG + DB
# ======================================================================
def _to_gemini_history_no_system(history_msgs: List[Dict[str, str]]) -> List[Dict]:
    out = []
    for m in history_msgs:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = "model" if role == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": content}]})
    return out


def _rewrite_db_answer(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    answer_text: str,
    lang_hint: str | None = None,
) -> str:
    if not REWRITE_DB_WITH_LLM:
        return answer_text

    lang_hint = (lang_hint or "vi").lower()
    if lang_hint.startswith("en"):
        lang_rule = "\nTrả lời bằng tiếng Anh. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
    else:
        lang_rule = (
            "\nTrả lời bằng tiếng Việt. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
        )

    guard = (
        SYSTEM_PRIMER
        + lang_rule
        + "\nYÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô.\n"
          "Không thêm bớt số. Nếu một số không cần thiết có quyền bỏ. "
          "Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
    )

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}",
                }
            ],
        }
    ]
    try:
        out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        out = strip_source_citations(out or "")
        has_num_old = re.search(r"\d", answer_text or "") is not None
        has_num_new = re.search(r"\d", out or "") is not None
        if has_num_old and not has_num_new:
            return answer_text
        return out or answer_text
    except Exception:
        return answer_text


def _rag_answer(
    user_text: str,
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    embeddings,
    retriever,
    lang_hint: str | None = None,
    session_id: str | None = None,
    session_doc_paths: Optional[List[str]] = None,
    only_use_session_docs: bool = False,
    focus_sources: Optional[List[str]] = None,
    file_meta_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[str, dict]:
    """
    Sinh câu trả lời bằng cách:
    - Lấy context từ file upload (ảnh + pdf/docx/txt) qua FAISS session (summary).
    - (Tuỳ) lấy thêm context từ global RAG.
    - Rerank → ghép vào 1 khối context → gửi Gemini.

    BẢO VỆ:
    - Không đưa các đoạn giống PROMPT HỆ THỐNG vào context.
    - Khi nhận diện đây là CÂU HỎI VỀ FILE (chỉ định tên file, 'nội dung', v.v.)
      thì KHÔNG ĐƯỢC trả về câu chào mặc định, mà phải mô tả/tóm tắt nội dung file.
    """

    session_doc_paths = session_doc_paths or []
    file_meta_map = file_meta_map or {}
    start_total = time.time()

    session_docs: List[Document] = []
    global_docs: List[Document] = []
    search_time_session = 0.0
    search_time_global = 0.0
    rerank_time = 0.0

    has_uploaded_files = bool(session_doc_paths)

    # ==========================================================
    # 1. Tìm trong file upload (session docs – summary ảnh + văn bản)
    # ==========================================================
    if has_uploaded_files and session_id:
        try:
            vs = _get_session_doc_vs(
                session_id=session_id,
                embeddings=embeddings,
                file_paths=session_doc_paths,
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
                file_meta_map=file_meta_map,
            )
            if vs is not None:
                t0 = time.time()
                session_docs = vs.similarity_search(user_text, k=20)
                search_time_session = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi khi tìm trong session docs: {e}")
            session_docs = []

    # Loại bỏ mọi doc mà nội dung là PROMPT HỆ THỐNG
    session_docs = _filter_internal_prompt_docs(session_docs)

    # Nếu user focus vào 1 hoặc vài file cụ thể → filter theo metadata["source"]
    if focus_sources:
        allowed = set(focus_sources)
        filtered = [
            d for d in session_docs
            if (d.metadata or {}).get("source") in allowed
        ]
        if filtered:
            print(
                f"[RAG] focus_sources={focus_sources} | "
                f"before={len(session_docs)} | after={len(filtered)}"
            )
            session_docs = filtered

    # ==========================================================
    # 2. Tìm trong global RAG (chỉ khi không chỉ dùng file upload)
    # ==========================================================
    if not only_use_session_docs:
        try:
            t0 = time.time()
            global_docs = retriever.get_relevant_documents("query: " + user_text)
            search_time_global = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi global RAG: {e}")
            global_docs = []

    # Loại prompt hệ thống khỏi global docs luôn
    global_docs = _filter_internal_prompt_docs(global_docs)

    # ==========================================================
    # 3. Gộp candidate + RERANK
    # ==========================================================
    if only_use_session_docs:
        all_candidates = session_docs
    else:
        all_candidates = session_docs + global_docs

    context_hint = ""

    if not all_candidates:
        # Không tìm được doc nào: fallback đọc raw từ file upload (nếu có)
        if only_use_session_docs and session_doc_paths:
            raw_snippets = []
            for p in session_doc_paths:
                try:
                    raw = _extract_text_from_uploaded_file(p)
                except Exception as e:
                    print(f"[RAG FALLBACK] Lỗi đọc file {p}: {e}")
                    raw = ""

                # Bỏ qua file mà bản thân nội dung là PROMPT HỆ THỐNG
                if raw and raw.strip() and not _is_internal_prompt_text(raw):
                    raw_snippets.append(raw[:4000])

            if raw_snippets:
                docs_text = "\n\n---\n\n".join(raw_snippets)
                context_hint = f"[DỮ LIỆU THAM KHẢO TỪ FILE UPLOAD]\n{docs_text}"
            else:
                context_hint = (
                    "(Không tìm thấy thông tin phù hợp trong các file bạn đã upload.)"
                )
        else:
            context_hint = "(Không tìm thấy thông tin phù hợp từ tài liệu nội bộ.)"
    else:
        # Có candidate → RERANK
        try:
            t0 = time.time()
            ranked = rerank(user_text, all_candidates, top_k=TOP_K)
            rerank_time = time.time() - t0

            parts = []
            for doc, score in ranked:
                txt = (doc.page_content or "").strip()
                if not txt:
                    continue

                # Bảo vệ thêm: nếu txt là prompt hệ thống thì skip luôn
                if _is_internal_prompt_text(txt):
                    continue

                if txt.lower().startswith("passage: "):
                    txt = txt[len("passage: "):].strip()

                meta = doc.metadata or {}
                src_name = (
                    meta.get("source")
                    or meta.get("title")
                    or os.path.basename(meta.get("path", ""))  # path có thể trống
                    or ""
                )
                is_summary = meta.get("is_summary", False)

                suffix = ""
                if src_name:
                    suffix = f" (Nguồn: {src_name}"
                    if is_summary:
                        suffix += " - Tóm tắt)"
                    else:
                        suffix += ")"
                else:
                    if is_summary:
                        suffix = " (Nguồn: tài liệu nội bộ - Tóm tắt)"
                    else:
                        suffix = " (Nguồn: tài liệu nội bộ)"

                parts.append(txt + suffix)

            if parts:
                docs_text = "\n\n---\n\n".join(parts)
                context_hint = f"[DỮ LIỆU THAM KHẢO]\n{docs_text}"
            else:
                context_hint = (
                    "(Không có đoạn nội dung nào phù hợp sau khi lọc prompt hệ thống.)"
                )
        except Exception as e:
            print(f"[RAG] Lỗi rerank: {e}")
            context_hint = "(Có lỗi khi xử lý tài liệu tham khảo.)"

    # ==========================================================
    # 4. Gọi LLM (Gemini) với SYSTEM_PRIMER + context RAG
    # ==========================================================
    lang = (lang_hint or "vi").lower()
    lang_instruction = (
        "\nTrả lời bằng tiếng Anh, rõ ràng, chuyên nghiệp."
        if lang.startswith("en")
        else "\nTrả lời bằng tiếng Việt, tự nhiên, dễ hiểu."
    )

    # ⚠️ Nhận diện đây có phải CÂU HỎI VỀ FILE không
    # Ở đây: nếu có file upload + only_use_session_docs=True thì hiểu là đang hỏi về file.
    is_file_question = bool(has_uploaded_files and only_use_session_docs)

    extra_file_rule = ""
    if is_file_question:
        extra_file_rule = """
QUAN TRỌNG (OVERRIDE):
- Người dùng đang hỏi về NỘI DUNG CÁC FILE đã upload (ảnh / pdf / docx / txt).
- Tuyệt đối KHÔNG coi đây là lời chào đơn thuần.
- KHÔNG sử dụng câu chào mặc định kiểu "Tôi là trợ lý ảo nội bộ của Tiximax Logistics. Tôi có thể hỗ trợ gì?".
- Bắt buộc phải:
  + Mô tả hoặc tóm tắt nội dung CÁC FILE đang được dùng làm ngữ cảnh.
  + Nếu người dùng liệt kê nhiều file (ví dụ: "vi-du-phieu-chi.jpg", "giay-bao-dien.png"),
    hãy trình bày RIÊNG cho từng file, ghi rõ file nào là file nào.
"""

    # SYSTEM_PRIMER là guardrail, không phải để AI mô tả lại.
    system_block = f"""{SYSTEM_PRIMER}
{lang_instruction}
{extra_file_rule}
"""

    user_block = f"""[NGỮ CẢNH NỘI BỘ / DỮ LIỆU THAM KHẢO]
{context_hint}

[NGƯỜI DÙNG HỎI]
{user_text}
"""

    # Lịch sử chat (không include system)
    hist_msgs = [
        m for m in get_history()
        if m.get("role") in ("user", "assistant")
    ]
    contents = _to_gemini_history_no_system(hist_msgs)

    # Thêm lượt cuối: system + context + câu hỏi
    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": f"[SYSTEM]\n{system_block}\n\n{user_block}"
                }
            ],
        }
    )

    result, llm_time = _safe_gemini_generate(
        gclient,
        GEMINI_MODEL,
        contents,
        GEN_CFG,
    )

    final_answer = strip_source_citations((result or "").strip())

    timing = {
        "embedding": 0.0,  # nếu sau này bạn đo embedding time thì set lại
        "search": round(search_time_session + search_time_global + rerank_time, 2),
        "llm": round(llm_time, 2),
        "total": round(time.time() - start_total, 2),
    }

    return final_answer, timing



# ======================================================================
# 6. HÀM CHÍNH: xử lý 1 lượt chat (sync)
# ======================================================================
def handle_chat_request(
    user_text: str,
    session_id: str,
    principal: Any,
    bm25_folder: Optional[Path] = None,
    corpus_path: Optional[Path] = None,
) -> dict:
    """
    Hàm xử lý 1 lượt chat sync:
    - Ưu tiên DB (handle_db_message)
    - Nếu không phải câu DB → RAG (global + session docs upload)
    - Hỗ trợ multi-file upload (list/dict) + ảnh (OCR → summary → RAG)
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return {"ok": False, "error": "Missing message"}

    full_start = time.time()

    # 0. Tạo session_id nếu chưa có
    if not session_id:
        try:
            info = create_new_session(
                session.get("user") or "",
                title="Cuộc trò chuyện mới",
            )
            session_id = info.get("session_id") or str(time.time())
        except Exception:
            session_id = str(time.time())

    # Lưu message user vào history
    add_message("user", user_text, session_id=session_id)

    # 1. Load LLM + RAG
    bm25_folder = bm25_folder or DATA_DIR
    corpus_path = corpus_path or (FAISS_ALL_DIR / "corpus.jsonl")
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model(
        bm25_folder=bm25_folder,
        corpus_path=corpus_path,
    )

    # 2. Load context & history
    ctx = _load_ctx(session_id)
    history_msgs = _get_history_msgs_for_ctx()

    # 3. Editor (dịch / viết lại câu trả lời trước)
    analysis = _analyze_followup_and_lang(
        gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
    )
    if analysis.get("mode") == "edit":
        final_answer = strip_source_citations(analysis.get("output", ""))
        add_message("assistant", final_answer, session_id=session_id)

        # cập nhật ngôn ngữ ưu tiên
        ctx["lang"] = analysis.get("set_lang") or ctx.get("lang", "vi")
        ctx["last_branch"] = "editor"
        update_ctx(session_id, ctx)

        return {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": "editor",
            "timing": {"total": round(time.time() - full_start, 2)},
        }

    # 4. Lệnh xoá file upload trong session
    if user_text.lower().strip() in ["xóa file", "xoá file", "hủy file", "delete file", "clear file"]:
        uploaded_files_meta = session.get("uploaded_files", [])
        session_doc_paths: List[str] = []

        # cố gắng log 1 file để debug (không bắt buộc)
        if isinstance(uploaded_files_meta, list):
            for item in reversed(uploaded_files_meta):
                if isinstance(item, dict):
                    p = item.get("path")
                    if p and os.path.exists(p):
                        session_doc_paths = [p]
                        print(f"[RAG] Đã nhận diện file: {p}")
                        break
        elif isinstance(uploaded_files_meta, dict) and session_id in uploaded_files_meta:
            for item in reversed(uploaded_files_meta[session_id]):
                if isinstance(item, dict):
                    p = item.get("path")
                    if p and os.path.exists(p):
                        session_doc_paths = [p]
                        print(f"[RAG] Đã nhận diện file từ dict: {p}")
                        break

        # Xoá metadata trong session
        if isinstance(uploaded_files_meta, dict):
            uploaded_files_meta.pop(session_id, None)
            session["uploaded_files"] = uploaded_files_meta
        else:
            session.pop("uploaded_files", None)

        # clear FAISS + summary cache
        _clear_session_doc_vs(session_id)

        final_answer = "Đã xoá toàn bộ file đã upload trong phiên này."
        add_message("assistant", final_answer, session_id=session_id)
        return {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": "doc_clear",
            "timing": {"total": round(time.time() - full_start, 2)},
        }

    # 5. Lấy file upload (multi-file + hỗ trợ cả list/dict)
    uploaded_files_meta = session.get("uploaded_files", [])
    session_doc_paths: List[str] = []
    seen_paths: set[str] = set()
    flat_metas: List[Dict[str, Any]] = []

    if isinstance(uploaded_files_meta, list):
        # format mới: session["uploaded_files"] = [ {name, stored_name, path, file_type}, ... ]
        flat_metas = [m for m in uploaded_files_meta if isinstance(m, dict)]
        for item in reversed(flat_metas):
            p = item.get("path")
            if (
                p
                and isinstance(p, str)
                and os.path.exists(p)
                and p not in seen_paths
            ):
                session_doc_paths.append(p)
                seen_paths.add(p)
    elif isinstance(uploaded_files_meta, dict):
        # format cũ: session["uploaded_files"][session_id] = [ {...}, ... ]
        meta_for_session = uploaded_files_meta.get(session_id) or []
        flat_metas = [m for m in meta_for_session if isinstance(m, dict)]
        if isinstance(meta_for_session, list):
            for item in reversed(meta_for_session):
                if not isinstance(item, dict):
                    continue
                p = item.get("path")
                if (
                    p
                    and isinstance(p, str)
                    and os.path.exists(p)
                    and p not in seen_paths
                ):
                    session_doc_paths.append(p)
                    seen_paths.add(p)

    # Map path → full meta (để lấy file_type / is_image nếu cần)
    file_meta_map: Dict[str, Dict[str, Any]] = {}
    for m in flat_metas:
        p = m.get("path")
        if p and isinstance(p, str):
            file_meta_map[p] = m

    active_file_path: Optional[str] = session_doc_paths[0] if session_doc_paths else None
    active_source: Optional[str] = os.path.basename(active_file_path) if active_file_path else None

    # 5.1 LLM detect câu kiểu "file này / 2 file này / các file trên..."
    is_generic_current = _is_generic_current_file_query(
        user_text=user_text,
        gclient=gclient,
        GEMINI_MODEL=GEMINI_MODEL,
        GEN_CFG=GEN_CFG,
    )

    # 5.2 Detect xem user có GÕ RÕ TÊN FILE trong câu hỏi không
    focus_sources: Optional[List[str]] = None
    if flat_metas:
        focus_sources = _detect_focus_sources_from_query(user_text, flat_metas)

    # Nếu chỉ có 1 file + câu kiểu "file này" → focus vào file đó
    if not focus_sources and is_generic_current and len(session_doc_paths) == 1 and active_source:
        focus_sources = [active_source]

    # Nếu user đã gõ rõ tên file → KHÔNG coi là "file này / file trên" nữa
    if focus_sources:
        is_generic_current = False

    # 5.3 NHÁNH ĐẶC BIỆT:
    # Nếu user hỏi rõ "nội dung các file" → tóm tắt từng file trực tiếp, không đi qua DB/RAG.
    if session_doc_paths and _is_request_uploaded_files_content(user_text):
        if focus_sources:
            allowed = set(focus_sources)
            target_paths = [
                p for p in session_doc_paths
                if os.path.basename(p) in allowed
            ]
        else:
            target_paths = _get_latest_batch_paths(flat_metas) or list(session_doc_paths)

        parts: List[str] = []
        for p in target_paths:
            meta_for_file = next(
                (m for m in flat_metas if m.get("path") == p),
                {},
            )
            display_name = meta_for_file.get("name") or os.path.basename(p)

            summary = _summarize_uploaded_file(
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
                path=p,
                max_lines=12,  # cho chi tiết hơn chút
            )
            summary = (summary or "").strip()
            if not summary:
                summary = "Không đọc được nội dung file này (có thể là ảnh/scan mờ hoặc file trống)."

            parts.append(f"{display_name}:\n{summary}")

        final_answer = (
            f"Bạn đã cung cấp {len(parts)} file, nội dung tóm tắt như sau:\n\n"
            + "\n\n".join(parts)
        )

        final_answer = strip_source_citations(final_answer)
        add_message("assistant", final_answer, session_id=session_id)
        ctx["last_branch"] = "file_direct_summary"
        try:
            update_ctx(session_id, ctx)
        except Exception:
            pass

        elapsed = time.time() - full_start
        return {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": ctx.get("last_branch", "file_direct_summary"),
            "meta": {},
            "timing": {
                "total": round(elapsed, 2),
            },
        }

    # 6. Cập nhật ngôn ngữ ưu tiên trong ctx
    if analysis.get("set_lang") in ("vi", "en"):
        ctx["lang"] = analysis.get("set_lang")
    elif "lang" not in ctx:
        ctx["lang"] = _auto_detect_lang(user_text)

    # 7. Kiểm tra DB trước (SQL / Supabase / hệ thống nội bộ)
    handled, db_answer, meta = handle_db_message(
        user_text,
        session_id,
        principal=principal,
    )

    if handled:
        # Có câu trả lời từ DB → cho Gemini rewrite cho gọn, giữ nguyên số liệu
        final_answer = _rewrite_db_answer(
            gclient,
            GEMINI_MODEL,
            GEN_CFG,
            db_answer,
            lang_hint=ctx.get("lang"),
        )
        ctx["last_branch"] = "db"
        timing = {}
    else:
        # 8. RAG – chọn subset file dùng trong lượt này + only_use_session_docs
        session_paths_for_rag = list(session_doc_paths)
        only_use_session_docs = False

        if session_doc_paths:
            # (1) LLM detect: câu hỏi có đang nói về FILE đã upload không?
            only_llm_file = _is_query_about_uploaded_file(
                user_text=user_text,
                lang=ctx.get("lang", "vi"),
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
            )
            only_use_session_docs = only_llm_file

            # (2) Nếu user GÕ RÕ TÊN FILE (focus_sources != None)
            if focus_sources:
                only_use_session_docs = True
                allowed = set(focus_sources)
                session_paths_for_rag = [
                    p for p in session_doc_paths
                    if os.path.basename(p) in allowed
                ]

            # (3) Nếu KHÔNG nêu tên file nhưng là câu “file này / ảnh này / 2 ảnh này…”
            elif is_generic_current and session_doc_paths:
                lower_q = user_text.lower()
                image_paths = []
                other_paths = []
                for p in session_doc_paths:
                    if is_image_path(p):
                        image_paths.append(p)
                    else:
                        other_paths.append(p)

                # CASE A: chỉ có ảnh
                if image_paths and not other_paths:
                    # mặc định dùng TẤT CẢ ảnh
                    n = len(image_paths)

                    # "2 ảnh / 3 hình / 2 phiếu / 2 hóa đơn ..."
                    m_num = re.search(
                        r'(\d+)\s*(file|tập tin|tap tin|ảnh|anh|hình|hinh|image|picture|'
                        r'phiếu|phieu|hóa đơn|hoa don|giấy|giay|tờ|to)',
                        lower_q,
                    )
                    if m_num:
                        try:
                            n = int(m_num.group(1))
                        except ValueError:
                            n = len(image_paths)
                    elif any(
                        kw in lower_q
                        for kw in [
                            "hai file", "hai ảnh", "hai anh", "hai hình", "hai hinh",
                            "hai phiếu", "hai phieu", "hai hóa đơn", "hai hoa don",
                        ]
                    ):
                        n = 2

                    # "các ảnh / những ảnh ..." → giữ n = len(image_paths)
                    n = max(1, min(n, len(image_paths)))

                    session_paths_for_rag = []
                    for i, p in enumerate(image_paths):
                        if i >= n:
                            break
                        session_paths_for_rag.append(p)

                    only_use_session_docs = True

                # CASE B: trộn cả doc + image
                else:
                    n = 1
                    m_num = re.search(
                        r'(\d+)\s*(file|tập tin|tap tin|tài liệu|tai lieu)',
                        lower_q,
                    )
                    if m_num:
                        try:
                            n = int(m_num.group(1))
                        except ValueError:
                            n = 1
                    elif any(
                        kw in lower_q
                        for kw in ["hai file", "hai tài liệu", "hai tai lieu"]
                    ):
                        n = 2
                    elif any(
                        kw in lower_q
                        for kw in ["các file", "cac file", "những file", "nhung file"]
                    ):
                        n = len(session_doc_paths)

                    n = max(1, min(n, len(session_doc_paths)))
                    session_paths_for_rag = session_doc_paths[:n]
                    only_use_session_docs = True

        print(
            f"[RAG MODE] session_id={session_id} | all_files={len(session_doc_paths)} "
            f"| used_files={len(session_paths_for_rag)} "
            f"| only_use_session_docs={only_use_session_docs} "
            f"| active_source={active_source} | is_generic_current={is_generic_current} "
            f"| focus_sources={focus_sources}"
        )

        # Gọi RAG chính (global + session docs)
        final_answer, timing = _rag_answer(
            user_text=user_text,
            gclient=gclient,
            GEMINI_MODEL=GEMINI_MODEL,
            GEN_CFG=GEN_CFG,
            embeddings=embeddings,
            retriever=retriever,
            lang_hint=ctx.get("lang"),
            session_id=session_id,
            session_doc_paths=session_paths_for_rag,
            only_use_session_docs=only_use_session_docs,
            focus_sources=focus_sources if focus_sources else None,
            file_meta_map=file_meta_map,
        )

        ctx["last_branch"] = "rag_file_only" if only_use_session_docs else "rag"
        if session_doc_paths:
            ctx["last_docs"] = [os.path.basename(p) for p in session_doc_paths]

    # 9. Ghi trả lời + cập nhật context
    final_answer = strip_source_citations(final_answer or "")
    add_message("assistant", final_answer, session_id=session_id)
    try:
        update_ctx(session_id, ctx)
    except Exception:
        pass

    # 10. Smart summary (hook, để nguyên nếu sau này cần)
    try:
        history = get_history()
        user_count = len([m for m in history if m.get("role") == "user"])
        if user_count >= 7 and user_count % 7 == 0:
            # có thể trigger auto-summary ở đây
            pass
    except Exception:
        pass

    elapsed = time.time() - full_start
    return {
        "ok": True,
        "answer": final_answer,
        "session_id": session_id,
        "branch": ctx.get("last_branch", "rag"),
        "meta": meta or {},
        "timing": {
            "total": round(elapsed, 2),
            **(timing if "timing" in locals() else {}),
        },
    }
