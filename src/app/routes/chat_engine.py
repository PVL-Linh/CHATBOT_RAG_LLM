from __future__ import annotations

import os
import re
import time
import json
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path

import fitz
import docx as docx_lib
import unicodedata
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

LLM_SEM = ChatConfig.LLM_SEM
DB_CONF_THRESHOLD = Chat_engine.DB_CONF_THRESHOLD
REWRITE_DB_WITH_LLM = Chat_engine.REWRITE_DB_WITH_LLM

# Mini FAISS cache cho tài liệu upload theo session
SESSION_DOC_VS: Dict[str, FAISS] = {}
SESSION_DOC_VS_META: Dict[str, Dict[str, float]] = {}


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
                time.sleep(backoff * (2**i))
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

    # Mở rộng pattern để match cả (Nguồn: ...) và các biến thể có dấu ngoặc, backslash, lỗi chính tả như "Biễu"
    text = re.sub(
        r'\s*\(?\s*[Nn]gu[oơ]n\s*:\s*[^\n\)]*\.(?:txt|docx|pdf)\s*\)?',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Loại bỏ các pattern khác như cũ, nhưng mở rộng để match path có backslash
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

    # Loại bỏ các path internal như Accountant\folder\file.txt
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

    return ""


def _summarize_uploaded_file(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    path: str,
    max_lines: int = 10,
) -> str:
    raw_text = _extract_text_from_uploaded_file(path)
    if not raw_text.strip():
        return ""

    detected_lang = _auto_detect_lang(raw_text)
    snippet = raw_text[:15000]  # Giới hạn để tránh quá dài

    prompt = f"""Tóm tắt tài liệu sau thành khoảng {max_lines} dòng chính.
- Giữ nguyên số liệu quan trọng, mã số, tên riêng, bảng biểu (dùng định dạng ASCII nếu cần).
- Tập trung vào nội dung cốt lõi, cấu trúc, ý chính.
- Bỏ chi tiết thừa, lặp lại.
- Trả lời bằng tiếng {'Việt' if detected_lang == 'vi' else 'Anh'}.

[TÀI LIỆU]
{snippet}
"""

    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    try:
        summary, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        return summary.strip() or raw_text[:2000]
    except Exception:
        return raw_text[:2000]


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
) -> Optional[FAISS]:
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
        for ch in chunks:
            texts.append(ch)
            metas.append({"source": src, "session_id": session_id})

    if not texts:
        return None

    vs = FAISS.from_texts(texts, embeddings, metadatas=metas)

    # 🔹 Lưu cả VS và meta file (path + mtime)
    SESSION_DOC_VS[session_id] = vs
    meta_map: Dict[str, float] = {}
    for p in file_paths:
        if p and os.path.exists(p):
            meta_map[p] = os.path.getmtime(p)
    SESSION_DOC_VS_META[session_id] = meta_map

    return vs


def _get_session_doc_vs(
    session_id: str,
    embeddings,
    file_paths: List[str],
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
) -> Optional[FAISS]:
    """
    Dùng summary + chunk để build FAISS cho session.
    Cache meta (mtime) + summary trong Redis để tránh build lại nếu file không đổi.
    """
    if not session_id or not file_paths:
        return None

    # Tính meta hiện tại từ file_paths
    current_meta: Dict[str, float] = {}
    for p in file_paths:
        if os.path.exists(p):
            try:
                current_meta[p] = os.path.getmtime(p)
            except Exception:
                continue

    # Lấy cached meta từ Redis (string)
    cached_meta_key = f"session_doc_vs_meta:{session_id}"
    cached_meta_raw = redis_client.get(cached_meta_key)
    cached_meta_str: Optional[str] = None

    if cached_meta_raw:
        if isinstance(cached_meta_raw, bytes):
            try:
                cached_meta_str = cached_meta_raw.decode("utf-8")
            except UnicodeDecodeError:
                cached_meta_str = None
        elif isinstance(cached_meta_raw, str):
            cached_meta_str = cached_meta_raw
        else:
            cached_meta_str = str(cached_meta_raw)

    cached_meta: Dict[str, float] = {}
    if cached_meta_str:
        try:
            cached_meta = json.loads(cached_meta_str)
        except json.JSONDecodeError:
            cached_meta = {}

    # Nếu meta khớp và VS cached tồn tại → dùng lại
    if SESSION_DOC_VS.get(session_id) and cached_meta == current_meta:
        return SESSION_DOC_VS.get(session_id)

    # Build mới từ summary
    texts: List[str] = []
    metas: List[Dict[str, Any]] = []

    for path in file_paths:
        if not os.path.exists(path):
            continue

        summary_key = f"file_summary:{session_id}:{os.path.basename(path)}"
        summary_raw = redis_client.get(summary_key)
        summary: Optional[str] = None

        if summary_raw:
            if isinstance(summary_raw, bytes):
                try:
                    summary = summary_raw.decode("utf-8")
                except UnicodeDecodeError:
                    summary = None
            elif isinstance(summary_raw, str):
                summary = summary_raw
            else:
                summary = str(summary_raw)

        if not summary or not summary.strip():
            summary = _summarize_uploaded_file(gclient, GEMINI_MODEL, GEN_CFG, path)
            if summary:
                # Lưu dạng unicode string cho đơn giản
                redis_client.set(summary_key, summary, ex=86400)

        if not summary or not summary.strip():
            continue

        chunks = _split_text_to_chunks(summary, max_chars=500, overlap=100)
        src = os.path.basename(path)
        for ch in chunks:
            texts.append(ch)
            metas.append({"source": src, "session_id": session_id, "is_summary": True})

    if not texts:
        return None

    vs = FAISS.from_texts(texts, embeddings, metadatas=metas)
    SESSION_DOC_VS[session_id] = vs

    # Cache meta mới dưới dạng string
    meta_json = json.dumps(current_meta)
    redis_client.set(cached_meta_key, meta_json, ex=86400)

    SESSION_DOC_VS_META[session_id] = current_meta
    return vs


def _clear_session_doc_vs(session_id: str) -> None:
    SESSION_DOC_VS.pop(session_id, None)
    SESSION_DOC_VS_META.pop(session_id, None)

    redis_client.delete(f"session_doc_vs_meta:{session_id}")
    keys = redis_client.keys(f"file_summary:{session_id}:*")
    if keys:
        redis_client.delete(*keys)


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
    Dùng Gemini để quyết định: người dùng có đang hỏi về nội dung của file đã upload không?
    Trả lời YES/NO.
    """
    if not gclient or not user_text.strip():
        return False

    query = user_text.strip()[:500]

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
) -> tuple[str, dict]:
    session_doc_paths = session_doc_paths or []
    start_total = time.time()

    session_docs: List[Document] = []
    global_docs: List[Document] = []
    search_time_session = 0.0
    search_time_global = 0.0
    rerank_time = 0.0

    has_uploaded_files = bool(session_doc_paths)

    # 1. Tìm trong file upload (summary VS)
    if has_uploaded_files:
        try:
            vs = _get_session_doc_vs(
                session_id=session_id,
                embeddings=embeddings,
                file_paths=session_doc_paths,
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
            )
            if vs is not None:
                t0 = time.time()
                session_docs = vs.similarity_search(user_text, k=20)
                search_time_session = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi khi tìm trong session docs: {e}")
            session_docs = []

    # 2. Global RAG (nếu được phép)
    if not only_use_session_docs:
        try:
            t0 = time.time()
            global_docs = retriever.get_relevant_documents("query: " + user_text)
            search_time_global = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi global RAG: {e}")

    # 3. Gộp & rerank
    all_candidates = session_docs + global_docs

    context_hint = ""
    if not all_candidates:
        if only_use_session_docs:
            context_hint = "(Không tìm thấy thông tin phù hợp trong file bạn đã upload.)"
        else:
            context_hint = "(Không tìm thấy thông tin phù hợp từ tài liệu nội bộ.)"
    else:
        try:
            t0 = time.time()
            ranked = rerank(user_text, all_candidates, top_k=TOP_K)
            rerank_time = time.time() - t0

            parts = []
            for doc, score in ranked:
                txt = doc.page_content
                if txt.lower().startswith("passage: "):
                    txt = txt[len("passage: "):]

                meta = doc.metadata
                src_name = meta.get("source") or meta.get("title") or os.path.basename(meta.get("path", ""))
                is_summary = meta.get("is_summary", False)

                suffix = f" (Nguồn: {src_name}"
                if is_summary:
                    suffix += " - Tóm tắt)"
                else:
                    suffix += ")"

                parts.append(txt.strip() + suffix)

            docs_text = "\n\n---\n\n".join(parts)
            context_hint = f"Dữ liệu tham khảo:\n{docs_text}"
        except Exception as e:
            print(f"[RAG] Lỗi rerank: {e}")
            context_hint = "(Có lỗi khi xử lý tài liệu tham khảo.)"

    # 4. SYSTEM PROMPT + GỌI LLM
    lang = (lang_hint or "vi").lower()
    lang_instruction = "\nTrả lời bằng tiếng Anh, rõ ràng, chuyên nghiệp." if lang.startswith("en") else "\nTrả lời bằng tiếng Việt, tự nhiên, dễ hiểu."

    system_prompt = f"""{SYSTEM_PRIMER}
{lang_instruction}

{context_hint}
"""

    hist_msgs = [
        m for m in get_history()
        if m.get("role") in ("user", "assistant")
    ]

    contents = _to_gemini_history_no_system(hist_msgs)
    contents.append({
        "role": "user",
        "parts": [{"text": f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_text}"}]
    })

    result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    final_answer = strip_source_citations(result.strip())

    timing = {
        "embedding": 0.0,
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
    user_text = (user_text or "").strip()
    if not user_text:
        return {"ok": False, "error": "Missing message"}

    full_start = time.time()

    # ====== Tạo session_id nếu chưa có ======
    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
            session_id = info.get("session_id") or str(time.time())
        except Exception:
            session_id = str(time.time())

    add_message("user", user_text, session_id=session_id)

    # ====== Load LLM + RAG ======
    bm25_folder = bm25_folder or DATA_DIR
    corpus_path = corpus_path or (FAISS_ALL_DIR / "corpus.jsonl")

    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model(
        bm25_folder=bm25_folder,
        corpus_path=corpus_path,
    )

    # ====== Load context & history ======
    ctx = _load_ctx(session_id)
    history_msgs = _get_history_msgs_for_ctx()

    # ====== 1. Xử lý dịch / viết lại ======
    analysis = _analyze_followup_and_lang(
        gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
    )

    if analysis.get("mode") == "edit":
        final_answer = strip_source_citations(analysis.get("output", ""))
        add_message("assistant", final_answer, session_id=session_id)
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

    # ====== 2. Xử lý lệnh xoá file ======
    if user_text.lower().strip() in ["xóa file", "xoá file", "hủy file", "delete file", "clear file"]:
        uploaded_files_meta = session.get("uploaded_files", None)

        # Nếu sau này bạn chuyển qua dạng dict {session_id: [...]}
        if isinstance(uploaded_files_meta, dict):
            uploaded_files_meta.pop(session_id, None)
            session["uploaded_files"] = uploaded_files_meta
        else:
            # Hiện tại vẫn là list → xoá hết như cũ
            session.pop("uploaded_files", None)

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

    # ====== 3. Lấy file upload ======
    uploaded_files_meta = session.get("uploaded_files", [])

    session_doc_paths: List[str] = []

    # Trường hợp hiện tại: uploaded_files_meta là list các dict {"path": ..., ...}
    if isinstance(uploaded_files_meta, list) and uploaded_files_meta:
        # Đi lùi từ file mới nhất về cũ → lấy file ĐẦU TIÊN có path tồn tại
        for item in reversed(uploaded_files_meta):
            if not isinstance(item, dict):
                continue
            p = item.get("path")
            if p and isinstance(p, str) and os.path.exists(p):
                session_doc_paths.append(p)
                break

    # Trường hợp tương lai: session["uploaded_files"] = { session_id: [ {path: ...}, ... ], ... }
    elif isinstance(uploaded_files_meta, dict):
        meta_for_session = uploaded_files_meta.get(session_id) or []
        if isinstance(meta_for_session, list) and meta_for_session:
            for item in reversed(meta_for_session):
                if not isinstance(item, dict):
                    continue
                p = item.get("path")
                if p and isinstance(p, str) and os.path.exists(p):
                    session_doc_paths.append(p)
                    break

    # ====== 4. Cập nhật ngôn ngữ ======
    if analysis.get("set_lang") in ("vi", "en"):
        ctx["lang"] = analysis.get("set_lang")
    elif "lang" not in ctx:
        ctx["lang"] = _auto_detect_lang(user_text)

    # ====== 5. Kiểm tra DB trước ======
    handled, db_answer, meta = handle_db_message(user_text, session_id, principal=principal)

    if handled:
        final_answer = _rewrite_db_answer(
            gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang")
        )
        ctx["last_branch"] = "db"
    else:
        # ====== 6. RAG – QUYẾT ĐỊNH CHỈ DÙNG FILE HAY CẢ GLOBAL ======
        only_use_session_docs = False
        if session_doc_paths:
            only_use_session_docs = _is_query_about_uploaded_file(
                user_text=user_text,
                lang=ctx.get("lang", "vi"),
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
            )
            print(f"[FILE DETECT] only_use_session_docs = {only_use_session_docs} | query: '{user_text}'")

        final_answer, timing = _rag_answer(
            user_text=user_text,
            gclient=gclient,
            GEMINI_MODEL=GEMINI_MODEL,
            GEN_CFG=GEN_CFG,
            embeddings=embeddings,
            retriever=retriever,
            lang_hint=ctx.get("lang"),
            session_id=session_id,
            session_doc_paths=session_doc_paths,
            only_use_session_docs=only_use_session_docs,
        )

        ctx["last_branch"] = "rag_file_only" if only_use_session_docs else "rag"
        if session_doc_paths:
            ctx["last_docs"] = [os.path.basename(p) for p in session_doc_paths]

    # ====== Ghi trả lời ====== 
    add_message("assistant", final_answer, session_id=session_id)

    # ====== Cập nhật context ======
    try:
        update_ctx(session_id, ctx)
    except Exception:
        pass

    # ====== Smart Summary ======
    try:
        history = get_history()
        user_count = len([m for m in history if m.get("role") == "user"])
        if user_count >= 7 and user_count % 7 == 0:
            # chỗ này bạn đang để pass, mình giữ nguyên
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
            **(timing if 'timing' in locals() else {}),
        },
    }

# from __future__ import annotations

# import os
# import re
# import time
# import json
# from typing import List, Dict, Any, Tuple, Optional
# from app.services.history import get_history, add_message
# from app.Model_LLM.Chat_Database.redis_ctx import redis_client
# from flask import (
#     Blueprint,
#     request,
#     jsonify,
#     session,
#     Response,
#     stream_with_context,
# )

# import fitz
# import docx as docx_lib
# from langchain_core.documents import Document
# from langchain_community.vectorstores import FAISS
# import unicodedata
# from app.Helpers.rate_limit import get_text_limiter
# from app.services.history import get_history, add_message, create_new_session
# from app.Helpers.prompt_internal import SYSTEM_PRIMER, sys_instr
# from app.Model_LLM.model_llm import LLM_model
# from app.Model_LLM.hybrid_retriever import rerank, TOP_K
# from app.config.settings import ChatConfig
# from app.Login.login_required import build_principal_from_session
# from app.Model_LLM.Chat_Database.db_router import handle_db_message
# from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx
# from app.config.paths import DATA_DIR, FAISS_ALL_DIR

# bp = Blueprint("chat", __name__)

# # ====== LLM helpers kept local to this module ======
# LLM_SEM = ChatConfig.LLM_SEM
# DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.65"))
# REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {
#     "0",
#     "false",
#     "False",
# }

# # Mini FAISS cache cho tài liệu upload theo session
# SESSION_DOC_VS: Dict[str, FAISS] = {}


# def _normalize_vi(text: str) -> str:
#     """
#     Chuẩn hoá tiếng Việt: bỏ dấu, về dạng ASCII thường để so pattern linh hoạt hơn.
#     Ví dụ: 'tóm tắt và dịch sang tiếng anh' -> 'tom tat va dich sang tieng anh'
#     """
#     if not text:
#         return ""
#     text = unicodedata.normalize("NFD", text)
#     text = "".join(ch for ch in text if not unicodedata.combining(ch))
#     return text

# def _extract_src_and_url(meta: dict) -> tuple[str, str]:
#     """
#     Helper: lấy tên tài liệu + url gọn từ metadata.
#     - Ưu tiên: title -> source -> filename -> basename(path)
#     - url ưu tiên: url -> link -> path (dùng path như url nội bộ)
#     """
#     if not isinstance(meta, dict):
#         return "", ""

#     src_name = (
#         meta.get("title")
#         or meta.get("source")
#         or meta.get("filename")
#         or ""
#     )

#     if not src_name and meta.get("path"):
#         src_name = os.path.basename(meta["path"])

#     url = meta.get("url") or meta.get("link") or meta.get("path") or ""

#     return src_name or "", url or ""

# def compress_dots(text: str, target: str = "...") -> str:
#     """
#     Gom các chuỗi nhiều dấu chấm liên tiếp (>=3) về 1 chuỗi chuẩn.
#     Mặc định: '.....' -> '...'
#     """
#     if not text:
#         return text
#     # .{3,} = mọi chuỗi có ít nhất 3 dấu chấm liên tiếp
#     return re.sub(r'\.{3,}', target, text)

# # ======================================================================
# # 1. HISTORY / CTX HELPERS
# # ======================================================================
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

# # ======================================================================
# # 3. EDITOR: DỊCH/VIẾT LẠI CÂU TRẢ LỜI TRƯỚC
# # ======================================================================
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

# # ======================================================================
# # 4. PHÂN TÍCH YÊU CẦU HIỆN TẠI: EDIT / PASS + NGÔN NGỮ
# # ======================================================================
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

#     # Việt → Anh
#     if any(p in lower_ut for p in vi_to_en_patterns):
#         out_text = _rewrite_last_answer_for_lang(
#             gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="en"
#         )
#         return {
#             "mode": "edit",
#             "output": out_text,
#             "set_lang": "en",
#         }

#     # Anh → Việt
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

#     if mode != "edit":
#         return {"mode": "pass", "output": "", "set_lang": set_lang}

#     if not output:
#         return {"mode": "pass", "output": "", "set_lang": set_lang}

#     return {"mode": "edit", "output": output, "set_lang": set_lang}

# # ======================================================================
# # 5. GEMINI WRAPPER
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

# # ======================================================================
# # 6. ĐỌC NỘI DUNG FILE UPLOAD + DỊCH FILE
# # ======================================================================
# _SOURCE_TAG_PAT = re.compile(
#     r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
#     re.IGNORECASE,
# )


# def strip_source_citations(text: str) -> str:
#     """
#     Làm sạch output:
#     - Bỏ mọi thông tin source/chunk/path nội bộ (.txt/.docx/.pdf)
#     - Giữ nguyên mọi URL thật (http/https)
#     - Gom chuỗi dấu chấm '.....' -> '...'
#     """
#     if not text:
#         return text

#     # 1) Xoá các đoạn dạng: source: "... .txt/.docx/.pdf" (có hoặc không ngoặc kép)
#     text = re.sub(
#         r'\bsource["\']?\s*:\s*["\']?[^"\n]*\.(?:txt|docx|pdf)["\']?',
#         '',
#         text,
#         flags=re.IGNORECASE,
#     )

#     # 2) Xoá các block [source: ...], [chunk_id: ...], [metadata: ...], [norm_case: ...]
#     text = re.sub(
#         r'[\(\[\{]\s*(?:source|chunk_id|metadata|norm_case)[\s:][^\)\]\}]{0,400}[\)\]\}]',
#         '',
#         text,
#         flags=re.IGNORECASE,
#     )

#     # 3) Xoá nguyên cụm ngoặc chứa link tới file nội bộ (KHÔNG phải http/https):
#     #    (link: Accountant\...\something.txt)
#     text = re.sub(
#         r'\(\s*[Ll]ink\s*:\s*(?!https?://)[^)]*\.(?:txt|docx|pdf)\s*\)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     # 4) Xoá trường hợp "link: ...file.txt" không có ngoặc, nhưng vẫn không đụng tới http/https
#     text = re.sub(
#         r'\b[Ll]ink\s*:\s*(?!https?://)[^\n]*\.(?:txt|docx|pdf)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     # 5) Xoá "Nguồn: ...file.txt" / "Nguồn: ...file.docx" nội bộ
#     text = re.sub(
#         r'\b[Nn]gu[oơ]n\s*:\s*[^\n]*\.(?:txt|docx|pdf)',
#         '',
#         text,
#         flags=re.DOTALL,
#     )

#     # 6) Dọn khoảng trắng thừa
#     text = re.sub(r'[ \t]{2,}', ' ', text)          # nhiều space -> 1 space
#     text = re.sub(r'\s+([.,!?;:])', r'\1', text)    # bỏ space trước dấu câu
#     text = re.sub(r'\(\s*\)', '', text)             # xoá ngoặc trống

#     # 7) Gom chuỗi dấu chấm: .......  -> ...
#     text = re.sub(r'\.{3,}', '...', text)

#     # 8) Strip hai đầu
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
#         start = end - overlap
#         if start < 0:
#             start = 0
#     return chunks


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
#     SESSION_DOC_VS[session_id] = vs
#     return vs


# def _get_session_doc_vs(
#     session_id: str,
#     embeddings,
#     file_paths: List[str],
# ) -> Optional[FAISS]:
#     if not session_id:
#         return None

#     vs = SESSION_DOC_VS.get(session_id)
#     if vs is not None:
#         return vs

#     if not file_paths:
#         return None

#     return _build_session_doc_vs(session_id, embeddings, file_paths)


# def _clear_session_doc_vs(session_id: str) -> None:
#     SESSION_DOC_VS.pop(session_id, None)


# def _is_translate_session_docs_request(user_text: str) -> bool:
#     """
#     Nhận diện các câu kiểu:
#     - 'dịch nội dung này sang tiếng anh'
#     - 'tóm tắt file và dịch sang tiếng anh'
#     - 'tóm tách file và dịch sang tiếng anh' (sai chính tả vẫn bắt)
#     - 'summarize and translate this file', ...
#     """
#     if not user_text:
#         return False

#     raw = user_text.strip().lower()
#     norm = _normalize_vi(raw).lower()

#     # 1) Các pattern “thẳng mặt” thường gặp (có dấu)
#     hard_patterns = [
#         "dịch nội dung này sang tiếng anh",
#         "dịch file này sang tiếng anh",
#         "dịch tài liệu này sang tiếng anh",
#         "dịch văn bản này sang tiếng anh",
#         "dịch nội dung trên sang tiếng anh",
#         "dịch đoạn trên sang tiếng anh",

#         "tóm tắt và dịch",
#         "tóm tắt file và dịch",
#         "tóm tắt nội dung này và dịch",
#         "tóm tắt tài liệu này và dịch",

#         "summarize and translate",
#         "summary and translate",
#         "summarise and translate",
#         "translate this file to english",
#         "translate this document to english",
#         "translate this doc to english",
#         "translate the above to english",
#     ]
#     if any(p in raw for p in hard_patterns):
#         return True

#     # 2) Pattern trên chuỗi không dấu (chống sai chính tả kiểu “tóm tách”)
#     #    Ví dụ: "tom tach file va dich sang tieng anh"
#     norm_patterns = [
#         "dich sang tieng anh",
#         "translate to english",
#         "to english",
#     ]
#     has_translate = any(p in norm for p in norm_patterns)
#     has_summary = (
#         "tom tat" in norm
#         or "tom tach" in norm
#         or "tom tac" in norm
#         or "tom tap" in norm  # phòng thêm lỗi gõ
#     )

#     if has_translate and has_summary:
#         return True

#     return False


# def _translate_session_docs(
#     user_text: str,
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     session_doc_paths: List[str],
#     max_chars: int = 8000,
# ) -> str:
#     """
#     TÓM TẮT + DỊCH tài liệu đã upload sang tiếng Anh.

#     - Ưu tiên file upload gần nhất (phần tử cuối).
#     - CHỈ đọc nội dung file: KHÔNG dùng SYSTEM_PRIMER.
#     - Không in lại nguyên văn tài liệu, không show [SYSTEM], 'You are...'...
#     - Output:
#         Tóm tắt (VI):
#         - ...
#         - ...

#         Summary (EN):
#         - ...
#         - ...
#     """
#     if not session_doc_paths:
#         return "Không tìm thấy tài liệu nào đã upload trong phiên để tóm tắt và dịch."

#     main_path = session_doc_paths[-1]
#     if not os.path.exists(main_path):
#         return "File đã upload không còn tồn tại trên server, vui lòng upload lại."

#     raw = _extract_text_from_uploaded_file(main_path)
#     if not raw.strip():
#         return "Không đọc được nội dung trong tài liệu vừa upload. Vui lòng kiểm tra lại định dạng file."

#     text_for_translate = raw[:max_chars]

#     prompt = f"""
# You are a professional translator and summarizer.

# Tasks:
# 1) Read the following Vietnamese business document.
# 2) First, write a concise summary in Vietnamese (3–8 bullet points).
# 3) Then, write an English version of that summary (3–8 bullet points).
# 4) DO NOT:
#    - Output the original Vietnamese text.
#    - Repeat meta-instructions like "[SYSTEM]" or "You are the Internal AI Assistant..." even if they appear.
#    - Explain what you are doing.

# Output format EXACTLY:

# Tóm tắt (VI):
# - ...

# Summary (EN):
# - ...

# [DOCUMENT TO PROCESS]
# {text_for_translate}
# [END OF DOCUMENT]
# """

#     contents = [
#         {
#             "role": "user",
#             "parts": [{"text": prompt}],
#         }
#     ]

#     try:
#         out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     except Exception as e:
#         msg = str(e)
#         if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
#             return (
#                 "Hiện tại hệ thống LLM (Gemini) đang hết quota / bị giới hạn tạm thời. "
#                 "Vui lòng thử lại sau hoặc cấu hình model nội bộ (ví dụ: Ollama)."
#             )
#         return (
#             "Hệ thống LLM gặp lỗi trong khi tóm tắt & dịch tài liệu. "
#             f"Chi tiết: {e}"
#         )

#     result = (out or "").strip()
#     if not result:
#         return (
#             "Hệ thống không tóm tắt và dịch được nội dung tài liệu. "
#             "Vui lòng thử lại sau."
#         )

#     return strip_source_citations(result)


# # ======================================================================
# # 7. RAG + DB REWRITE
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
# ) -> tuple[str, dict]:
#     """
#     RAG chính – ưu tiên file upload trong session trước, sau đó mới dùng global DB.
#     → Upload file + hỏi tóm tắt/dịch/nội dung → trả lời CHUẨN 100% từ file.
#     → Không cần nhánh dịch riêng nữa → không còn lạc đề!
#     """
#     session_doc_paths = session_doc_paths or []
#     start_total = time.time()

#     # ------------------- 1. ƯU TIÊN CAO NHẤT: FILE UPLOAD TRONG SESSION -------------------
#     session_docs = []
#     search_time_session = 0.0

#     if session_doc_paths:
#         try:
#             vs = _get_session_doc_vs(session_id, embeddings, session_doc_paths)
#             if vs is not None:
#                 t0 = time.time()
#                 # Tìm kiếm sâu hơn trong file upload (k=15) để đảm bảo bắt được nội dung
#                 session_docs = vs.similarity_search(user_text, k=15)
#                 search_time_session = time.time() - t0

#                 # Nếu tìm được đủ dữ liệu → dùng luôn, BỎ QUA global DB
#                 if len(session_docs) >= 3:
#                     parts = []
#                     for doc in session_docs:
#                         src = doc.metadata.get("source", "file upload")
#                         txt = doc.page_content.strip()
#                         if txt.lower().startswith("passage: "):
#                             txt = txt[len("passage: "):]
#                         parts.append(f"[Từ file: {src}]\n{txt}")
#                     docs_text = "\n\n---\n\n".join(parts)

#                     context_hint = f"Context (từ tài liệu người dùng vừa upload):\n{docs_text}"
#                     # → Dùng context này → hỏi gì cũng đúng: tóm tắt, dịch, nội dung...
#                 else:
#                     session_docs = []
#         except Exception as e:
#             print(f"[RAG] Lỗi khi tìm trong session docs: {e}")
#             session_docs = []

#     # ------------------- 2. NẾU KHÔNG ĐỦ DỮ LIỆU TỪ FILE → DÙNG GLOBAL DB -------------------
#     if not session_docs:
#         try:
#             t0 = time.time()
#             global_docs = retriever.get_relevant_documents("query: " + user_text)
#             search_time_global = time.time() - t0
#         except Exception:
#             global_docs = []

#         all_candidates = global_docs
#         search_time_session = 0.0
#     else:
#         all_candidates = session_docs
#         search_time_global = 0.0

#     # ------------------- 3. RERANK (nếu có dữ liệu) -------------------
#     rerank_time = 0.0
#     docs_text = ""
#     try:
#         t0 = time.time()
#         ranked = rerank(user_text, all_candidates, top_k=TOP_K)
#         parts = []
#         for d, _score in ranked:
#             txt = d.page_content
#             if txt.lower().startswith("passage: "):
#                 txt = txt[len("passage: "):]
#             src_name, url = _extract_src_and_url(d.metadata)
#             suffix = f" (Nguồn: {src_name})" if src_name else ""
#             if url and "http" in url:
#                 suffix += f" | Link: {url}"
#             parts.append(txt + suffix)
#         docs_text = "\n\n---\n\n".join(parts) if parts else ""
#         rerank_time = time.time() - t0
#     except Exception as e:
#         print(f"[RAG] Lỗi rerank: {e}")

#     # ------------------- 4. TẠO CONTEXT CHO LLM -------------------
#     if docs_text:
#         context_hint = f"Dữ liệu tham khảo:\n{docs_text}"
#     else:
#         context_hint = "(Không tìm thấy thông tin phù hợp từ tài liệu.)"

#     # Xác định ngôn ngữ trả lời
#     lang = (lang_hint or "vi").lower()
#     if lang.startswith("en"):
#         lang_instruction = "\nTrả lời bằng tiếng Anh, rõ ràng, chuyên nghiệp."
#     else:
#         lang_instruction = "\nTrả lời bằng tiếng Việt, tự nhiên, dễ hiểu."

#     system_prompt = f"""{SYSTEM_PRIMER}
# {lang_instruction}

# {context_hint}
# """

#     # ------------------- 5. TẠO PROMPT CHO GEMINI -------------------
#     hist_msgs = [
#         {"role": m["role"], "content": m["content"]}
#         for m in get_history()
#         if m["role"] in ("user", "assistant")
#     ]
#     contents = _to_gemini_history_no_system(hist_msgs)
#     contents.append({
#         "role": "user",
#         "parts": [{"text": f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_text}"}]
#     })

#     # ------------------- 6. GỌI LLM -------------------
#     try:
#         result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     except Exception as e:
#         error_msg = "Hệ thống đang bận. Vui lòng thử lại sau."
#         if "quota" in str(e).lower() or "resource_exhausted" in str(e).lower():
#             error_msg = "Hệ thống LLM tạm thời hết quota. Vui lòng thử lại sau ít phút."
#         result, llm_time = error_msg, 0.0

#     # Làm sạch source citation
#     final_answer = strip_source_citations(result.strip())

#     # ------------------- 7. TRẢ KẾT QUẢ + TIMING -------------------
#     timing = {
#         "embedding": 0.0,
#         "search": round(search_time_global + search_time_session + rerank_time, 2),
#         "llm": round(llm_time, 2),
#         "total": round(time.time() - start_total, 2),
#     }

#     return final_answer, timing

# # ======================================================================
# # 8. HTTP ENDPOINTS
# # ======================================================================
# @bp.route("/api/chat", methods=["POST"])
# def chat_api():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model(
#     bm25_folder=DATA_DIR,
#     corpus_path=FAISS_ALL_DIR / "corpus.jsonl",
#     )


#     data = request.get_json(force=True) or {}
#     user_text = (data.get("message") or "").strip()
#     session_id = (data.get("session_id") or "").strip()

#     principal = build_principal_from_session()

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     if not session_id:
#         try:
#             info = create_new_session(
#                 session.get("user") or "", title="Cuộc trò chuyện mới"
#             )
#             session_id = info.get("session_id") or ""
#         except Exception:
#             session_id = ""

#     # Ghi tin nhắn người dùng trước (để history chính xác khi đếm)
#     add_message("user", user_text, session_id=session_id)

#     full_start = time.time()

#     # ==== LOAD CTX & PHÂN TÍCH NGỮ CẢNH + NGÔN NGỮ ====
#     ctx = _load_ctx(session_id)
#     history_msgs = _get_history_msgs_for_ctx()

#     analysis = _analyze_followup_and_lang(
#         gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
#     )

#     new_lang = analysis.get("set_lang")
#     if new_lang in ("vi", "en"):
#         ctx["lang"] = new_lang
#     else:
#         if "lang" not in ctx:
#             detected = _auto_detect_lang(user_text)
#             ctx["lang"] = detected

#     # ==== NHÁNH EDITOR: chỉ chỉnh sửa/dịch câu trả lời trước ====
#     if analysis.get("mode") == "edit":
#         final_answer = strip_source_citations(analysis.get("output") or "")
#         add_message("assistant", final_answer, session_id=session_id)

#         try:
#             ctx_to_save = dict(ctx)
#             ctx_to_save["last_branch"] = "editor"
#             update_ctx(session_id, ctx_to_save)
#         except Exception:
#             pass

#         elapsed = time.time() - full_start
#         return jsonify(
#             {
#                 "ok": True,
#                 "answer": final_answer,
#                 "session_id": session_id,
#                 "branch": "editor",
#                 "meta": {"editor": {"mode": "edit", "set_lang": ctx.get("lang")}},
#                 "timing": {
#                     "total": round(elapsed, 2),
#                     "embedding": 0.0,
#                     "search": 0.0,
#                     "llm": round(elapsed, 2),
#                 },
#             }
#         )

#     # ==== XÓA FILE UPLOAD (nếu yêu cầu) ====
#     normalized = user_text.lower().strip()
#     if normalized in ["xóa file", "xoá file", "hủy file", "huy file", "delete file"]:
#         session.pop("uploaded_files", None)
#         session.pop("session_docs_dirty", None)
#         _clear_session_doc_vs(session_id)

#         final_answer = "Đã xoá danh sách file đã upload trong phiên hiện tại. Các câu hỏi tiếp theo sẽ chỉ dùng DB/RAG global."
#         add_message("assistant", final_answer, session_id=session_id)
#         elapsed = time.time() - full_start
#         return jsonify(
#             {
#                 "ok": True,
#                 "answer": final_answer,
#                 "session_id": session_id,
#                 "branch": "doc_clear",
#                 "meta": {"doc_qa": {"cleared": True}},
#                 "timing": {"total": round(elapsed, 2), "embedding": 0.0, "search": 0.0, "llm": 0.0},
#             }
#         )

#     # ==== LẤY DANH SÁCH FILE UPLOAD ====
#     uploaded_files_meta = session.get("uploaded_files", [])
#     session_doc_paths: list[str] = []
#     if isinstance(uploaded_files_meta, list):
#         for item in uploaded_files_meta:
#             if isinstance(item, dict):
#                 p = item.get("path")
#                 if p and isinstance(p, str) and os.path.exists(p):
#                     session_doc_paths.append(p)

#     # # ==== NHÁNH DỊCH / TÓM TẮT FILE ====
#     # if session_doc_paths and _is_translate_session_docs_request(user_text):
#     #     final_answer = _translate_session_docs(
#     #         user_text, gclient, GEMINI_MODEL, GEN_CFG, session_doc_paths
#     #     )
#     #     add_message("assistant", final_answer, session_id=session_id)

#     #     try:
#     #         ctx_to_save = dict(ctx)
#     #         ctx_to_save["lang"] = "en"
#     #         ctx_to_save["last_branch"] = "doc_translate"
#     #         ctx_to_save["last_docs"] = [os.path.basename(p) for p in session_doc_paths]
#     #         update_ctx(session_id, ctx_to_save)
#     #     except Exception:
#     #         pass

#     #     elapsed = time.time() - full_start
#     #     return jsonify(
#     #         {
#     #             "ok": True,
#     #             "answer": final_answer,
#     #             "session_id": session_id,
#     #             "branch": "doc_translate",
#     #             "meta": {"doc_translate": {"files_used": session_doc_paths[-1:]}},
#     #             "timing": {"total": round(elapsed, 2), "embedding": 0.0, "search": 0.0, "llm": round(elapsed, 2)},
#     #         }
#     #     )

#     # ==== NHÁNH DB TRƯỚC ====
#     handled, db_answer, meta = handle_db_message(user_text, session_id, principal=principal)
#     branch = "db" if handled else "rag"
#     timing = {"embedding": 0.0, "search": 0.0, "llm": 0.0}

#     if handled:
#         final_answer = _rewrite_db_answer(gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang"))
#         try:
#             ctx_to_save = dict(ctx)
#             if isinstance(meta, dict):
#                 if meta.get("intent"):
#                     ctx_to_save["last_intent"] = meta.get("intent")
#                 if meta.get("time_window"):
#                     ctx_to_save["time_window"] = meta.get("time_window")
#             ctx_to_save["last_branch"] = "db"
#             update_ctx(session_id, ctx_to_save)
#         except Exception:
#             pass
#     else:
#         # ==== NHÁNH RAG ====
#         final_answer, timing = _rag_answer(
#             user_text,
#             gclient,
#             GEMINI_MODEL,
#             GEN_CFG,
#             embeddings,
#             retriever,
#             lang_hint=ctx.get("lang"),
#             session_id=session_id,
#             session_doc_paths=session_doc_paths,
#         )
#         try:
#             ctx_to_save = dict(ctx)
#             ctx_to_save["last_branch"] = "rag"
#             if session_doc_paths:
#                 ctx_to_save["last_docs"] = [os.path.basename(p) for p in session_doc_paths]
#             update_ctx(session_id, ctx_to_save)
#         except Exception:
#             pass
#     add_message("assistant", final_answer, session_id=session_id)
#     try:

#         history = get_history()
#         user_messages_count = len([m for m in history if m.get("role") == "user"])
#         if user_messages_count >= 7 and user_messages_count % 7 == 0:
#             summary_prompt = (
#                 "Bạn là trợ lý nội bộ cực kỳ thông minh. Hãy tóm tắt cuộc trò chuyện sau đây sao cho "
#                 "vẫn giữ được toàn bộ ngữ cảnh quan trọng, chi tiết quy trình, biểu mẫu, số tiền, "
#                 "tên người/tên phòng ban đã nhắc đến (nếu có). Viết dưới góc nhìn thứ nhất như người dùng đang nói.\n"
#                 "Độ dài: 3–5 câu, tối đa 250 từ. Bắt đầu bằng 'Người dùng đang hỏi về...'\n\n"
#                 "Cuộc trò chuyện gần nhất:\n"
#                 + "\n".join([f"{m['role']}: {m['content'][:800]}" for m in history[-15:]])
#                 + "\n\nTóm tắt:"
#             )

#             from google.generativeai import GenerativeModel
#             summary_model = GenerativeModel("gemini-2.0-flash")
#             summary_resp = summary_model.generate_content(
#                 summary_prompt,
#                 generation_config={
#                     "temperature": 0.4,
#                     "max_output_tokens": 300,
#                     "top_p": 0.95
#                 }
#             )
#             summary_text = summary_resp.text.strip()

#             redis_client.delete(f"history:{session_id}")
#             redis_client.delete(f"ctx:{session_id}")
#             redis_client.delete(f"session_doc_vs:{session_id}")
#             add_message(session_id, "system", f"[TÓM TẮT NGỮ CẢNH]: {summary_text}")
#             add_message(session_id, "user", user_text)

#             print(f"[SMART SUMMARY] Đã tóm tắt & reset Redis cho session {session_id}")

#     except Exception as e:
#         print(f"[SUMMARY ERROR] {e}")

#     elapsed = time.time() - full_start
#     return jsonify(
#         {
#             "ok": True,
#             "answer": final_answer,
#             "session_id": session_id,
#             "branch": branch,
#             "meta": meta,
#             "timing": {
#                 "total": round(elapsed, 2),
#                 **timing,
#             },
#         }
#     )


# @bp.route("/chat", methods=["POST"])
# def chat_api_alias():
#     return chat_api()


# @bp.route("/api/chat/stream", methods=["POST"])
# def chat_stream():
#     """
#     Stream mode: vẫn giữ đơn giản (không merge RAG session cho nhẹ).
#     """
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
#     data = request.get_json(force=True) or {}
#     user_text = (data.get("message") or "").strip()
#     session_id = (data.get("session_id") or "").strip()

#     principal = build_principal_from_session()

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     if not session_id:
#         try:
#             info = create_new_session(
#                 session.get("user") or "", title="Cuộc trò chuyện mới"
#             )
#             session_id = info.get("session_id") or ""
#         except Exception:
#             session_id = ""

#     add_message("user", user_text, session_id=session_id)

#     ctx = _load_ctx(session_id)
#     history_msgs = _get_history_msgs_for_ctx()

#     analysis = _analyze_followup_and_lang(
#         gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
#     )

#     new_lang = analysis.get("set_lang")
#     if new_lang in ("vi", "en"):
#         ctx["lang"] = new_lang
#     else:
#         if "lang" not in ctx:
#             detected = _auto_detect_lang(user_text)
#             ctx["lang"] = detected

#     # EDITOR trong stream: trả JSON luôn
#     if analysis.get("mode") == "edit":
#         final_answer = strip_source_citations(analysis.get("output") or "")
#         add_message("assistant", final_answer, session_id=session_id)

#         try:
#             ctx_to_save = dict(ctx)
#             ctx_to_save["last_branch"] = "editor"
#             update_ctx(session_id, ctx_to_save)
#         except Exception:
#             pass

#         return jsonify(
#             {
#                 "ok": True,
#                 "answer": final_answer,
#                 "session_id": session_id,
#                 "branch": "editor",
#                 "meta": {"editor": {"mode": "edit", "set_lang": ctx.get("lang")}},
#             }
#         )

#     # DB trước
#     handled, db_answer, meta = handle_db_message(
#         user_text, session_id, principal=principal
#     )
#     if handled:
#         final_answer = _rewrite_db_answer(
#             gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang")
#         )
#         add_message("assistant", final_answer, session_id=session_id)

#         try:
#             ctx_to_save = dict(ctx)
#             if isinstance(meta, dict):
#                 if meta.get("intent"):
#                     ctx_to_save["last_intent"] = meta.get("intent")
#                 if meta.get("time_window"):
#                     ctx_to_save["time_window"] = meta.get("time_window")
#             ctx_to_save["last_branch"] = "db"
#             update_ctx(session_id, ctx_to_save)
#         except Exception:
#             pass

#         return jsonify(
#             {
#                 "ok": True,
#                 "answer": final_answer,
#                 "session_id": session_id,
#                 "branch": "db",
#                 "meta": meta,
#             }
#         )

#     # Stream RAG đơn giản
#     hist_msgs = [
#         {"role": m["role"], "content": m["content"]}
#         for m in get_history()
#         if m["role"] in ("user", "assistant")
#     ]
#     contents = _to_gemini_history_no_system(hist_msgs)
#     context_hint = "(Stream mode - context omitted)"

#     lang_hint = (ctx.get("lang") or "vi").lower()
#     if lang_hint.startswith("en"):
#         lang_instruction = "\nNgôn ngữ trả lời: tiếng Anh."
#     else:
#         lang_instruction = "\nNgôn ngữ trả lời: tiếng Việt (ưu tiên)."

#     system_prompt = f"""{SYSTEM_PRIMER}
# {lang_instruction}
# {context_hint}
# """
#     first_user_text = f"""[SYSTEM]
# {system_prompt}

# [USER]
# {user_text}"""
#     contents.append({"role": "user", "parts": [{"text": first_user_text}]})

#     limiter = get_text_limiter()
#     tokens_est = _estimate_from_contents(
#         contents, GEN_CFG.get("max_output_tokens", 1024)
#     )

#     def gen():
#         yield f"event: ready\ndata: {json.dumps({'session_id': session_id, 'branch': 'rag'})}\n\n"
#         try:
#             limiter.acquire(tokens_est)
#             with LLM_SEM:
#                 resp = gclient.models.generate_content(
#                     model=GEMINI_MODEL,
#                     contents=contents,
#                     config=GEN_CFG,
#                     stream=True,
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
#             full_answer = strip_source_citations("".join(acc).strip())
#             add_message("assistant", full_answer, session_id=session_id)

#             try:
#                 ctx_to_save = dict(ctx)
#                 ctx_to_save["last_branch"] = "rag"
#                 update_ctx(session_id, ctx_to_save)
#             except Exception:
#                 pass

#             yield "event: done\ndata: {}\n\n"
#         except Exception as e:
#             limiter.on_429()
#             msg = str(e)
#             if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
#                 friendly = (
#                     "Hiện tại hệ thống LLM (Gemini) đang hết quota / bị giới hạn tạm thời. "
#                     "Vui lòng thử lại sau hoặc cấu hình model nội bộ (ví dụ: Ollama)."
#                 )
#             else:
#                 friendly = (
#                     "Hệ thống LLM đang gặp sự cố trong lúc stream câu trả lời. "
#                     "Vui lòng thử lại sau."
#                 )
#             yield f"event: error\ndata: {json.dumps({'message': friendly})}\n\n"

#     return Response(
#         stream_with_context(gen()),
#         mimetype="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache",
#             "X-Accel-Buffering": "no",
#         },
#     )
