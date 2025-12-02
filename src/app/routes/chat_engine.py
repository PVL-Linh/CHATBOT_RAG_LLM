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

# ✅ mới: import module xử lý ảnh
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

def _detect_focus_sources_from_query(
    user_text: str,
    uploaded_files_meta: List[Dict[str, Any]],
) -> Optional[List[str]]:
    """
    Tìm xem câu hỏi đang nhắc tới file nào (hoặc nhiều file nào).
    Trả về danh sách basename (stored_name) để khớp với metadata["source"] trong FAISS.
    Nếu không match được file nào thì trả về None (nghĩa là dùng tất cả file).
    """
    if not user_text or not uploaded_files_meta:
        return None

    q = user_text.lower()
    matched_sources: List[str] = []

    for item in uploaded_files_meta:
        if not isinstance(item, dict):
            continue

        name = (item.get("name") or "").lower()           # vi-du-phieu-chi.jpg
        stored = (item.get("stored_name") or "").lower()  # 1764_vi-du-phieu-chi.jpg
        path = (item.get("path") or "").lower()

        # basename để khớp với metadata["source"]
        basename = os.path.basename(path or stored or name)
        basename_lower = basename.lower()

        candidates = [
            name,
            stored,
            os.path.splitext(name)[0],            # vi-du-phieu-chi
            os.path.splitext(basename_lower)[0],  # 1764_vi-du-phieu-chi -> 1764_vi-du-phieu-chi
        ]

        for c in candidates:
            if c and c in q:
                if basename not in matched_sources:
                    matched_sources.append(basename)
                break

    if not matched_sources:
        return None

    return matched_sources

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
            {"role": m["role"], "content": m["content"]}  # type: ignore
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
# 2. DETECT NGÔN NGỮ ĐƠN GIẢN + QUERY FILE
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


def _is_generic_current_file_query(user_text: str) -> bool:
    if not user_text:
        return False

    t = user_text.lower()

    patterns = [
        # file chung chung
        "file trên", "file tren",
        "file nay", "file này",
        "file vua roi", "file vừa rồi",
        "file moi up", "file mới up",
        "file hien tai", "file hiện tại",
        "thong tin cua file", "thông tin của file",
        "noi dung file", "nội dung file",
        "tom tat file", "tóm tắt file",

        # hóa đơn
        "hóa đơn này", "hoa don nay",
        "hóa đơn trên", "hoa don tren",
        "thông tin của hóa đơn này", "thong tin cua hoa don nay",
        "tổng tiền của hóa đơn này", "tong tien cua hoa don nay",

        # ảnh / hình
        "ảnh này", "anh nay",
        "hình này", "hinh nay",
        "ảnh trên", "anh tren",
        "hình trên", "hinh tren",
    ]

    return any(p in t for p in patterns)


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

    # ===== ẢNH: gọi utils riêng =====
    if is_image_path(path):
        return extract_text_from_image(path)

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
    snippet = raw_text[:15000]

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
        except Exception as e:
            print(f"[RAG] Lỗi extract file {path}: {e}")
            raw = ""
        if not raw.strip():
            continue

        chunks = _split_text_to_chunks(raw, max_chars=800, overlap=200)
        src = os.path.basename(path)
        for ch in chunks:
            texts.append(ch)
            metas.append({"source": src, "session_id": session_id, "is_summary": False})

    if not texts:
        return None

    vs = FAISS.from_texts(texts, embeddings, metadatas=metas)

    SESSION_DOC_VS[session_id] = vs
    meta_map: Dict[str, float] = {}
    for p in file_paths:
        if p and os.path.exists(p):
            meta_map[p] = os.path.getmtime(p)
    SESSION_DOC_VS_META[session_id] = meta_map

    try:
        meta_json = json.dumps(meta_map)
        redis_client.set(f"session_doc_vs_meta:{session_id}", meta_json, ex=86400)
    except Exception as e:
        print(f"[RAG] Lỗi ghi Redis meta cho session {session_id}: {e}")

    return vs


def _get_session_doc_vs(
    session_id: str,
    embeddings,
    file_paths: List[str],
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
) -> Optional[FAISS]:
    if not session_id or not file_paths:
        return None

    current_meta: Dict[str, float] = {}
    for p in file_paths:
        if os.path.exists(p):
            try:
                current_meta[p] = os.path.getmtime(p)
            except Exception:
                continue

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

    if SESSION_DOC_VS.get(session_id) and cached_meta == current_meta:
        return SESSION_DOC_VS.get(session_id)

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

    try:
        meta_json = json.dumps(current_meta)
        redis_client.set(cached_meta_key, meta_json, ex=86400)
    except Exception as e:
        print(f"[RAG] Lỗi ghi Redis meta (summary) cho session {session_id}: {e}")

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
    focus_sources: Optional[List[str]] = None,
) -> tuple[str, dict]:
    session_doc_paths = session_doc_paths or []
    start_total = time.time()

    session_docs: List[Document] = []
    global_docs: List[Document] = []
    search_time_session = 0.0
    search_time_global = 0.0
    rerank_time = 0.0

    has_uploaded_files = bool(session_doc_paths)

    if has_uploaded_files and session_id:
        try:
            vs = SESSION_DOC_VS.get(session_id)

            current_meta: Dict[str, float] = {}
            for p in session_doc_paths:
                if os.path.exists(p):
                    try:
                        current_meta[p] = os.path.getmtime(p)
                    except Exception:
                        continue

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

            rebuild = False
            if vs is None or cached_meta != current_meta:
                rebuild = True

            if rebuild:
                vs = _build_session_doc_vs(
                    session_id=session_id,
                    embeddings=embeddings,
                    file_paths=session_doc_paths,
                )

            if vs is not None:
                t0 = time.time()
                session_docs = vs.similarity_search(user_text, k=20)
                search_time_session = time.time() - t0
                print(f"[RAG] session_docs from file = {len(session_docs)}")
            else:
                session_docs = []
        except Exception as e:
            print(f"[RAG] Lỗi khi tìm trong session docs: {e}")
            session_docs = []

    # 🔍 Filter theo 1 hoặc nhiều file cụ thể
    if focus_sources:
        allowed = set(focus_sources)
        filtered = [
            d for d in session_docs
            if (d.metadata or {}).get("source") in allowed
        ]
        if filtered:
            print(
                f"[RAG] focus_sources={focus_sources} | before={len(session_docs)} | after={len(filtered)}"
            )
            session_docs = filtered

    if not only_use_session_docs:
        try:
            t0 = time.time()
            global_docs = retriever.get_relevant_documents("query: " + user_text)
            search_time_global = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi global RAG: {e}")

    if only_use_session_docs:
        all_candidates = session_docs
    else:
        all_candidates = session_docs + global_docs

    print(
        f"[RAG] session_docs={len(session_docs)} | global_docs={len(global_docs)} "
        f"| only_use_session_docs={only_use_session_docs}"
    )

    context_hint = ""
    if not all_candidates:
        if only_use_session_docs and session_doc_paths:
            raw_snippets = []
            for p in session_doc_paths:
                try:
                    raw = _extract_text_from_uploaded_file(p)
                except Exception as e:
                    print(f"[RAG FALLBACK] Lỗi đọc file {p}: {e}")
                    raw = ""
                if raw and raw.strip():
                    raw_snippets.append(raw[:4000])

            if raw_snippets:
                docs_text = "\n\n---\n\n".join(raw_snippets)
                context_hint = f"Dữ liệu tham khảo từ file upload:\n{docs_text}"
            else:
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

                meta = doc.metadata or {}
                src_name = meta.get("source") or meta.get("title") or os.path.basename(meta.get("path", "")) or ""
                is_summary = meta.get("is_summary", False)

                suffix = f" (Nguồn: {src_name}" if src_name else " (Nguồn: tài liệu)"
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

    lang = (lang_hint or "vi").lower()
    lang_instruction = (
        "\nTrả lời bằng tiếng Anh, rõ ràng, chuyên nghiệp."
        if lang.startswith("en")
        else "\nTrả lời bằng tiếng Việt, tự nhiên, dễ hiểu."
    )

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

    # ✅ Gọi đúng chữ ký hàm: (gclient, model, contents, config)
    result, llm_time = _safe_gemini_generate(
        gclient,
        GEMINI_MODEL,
        contents,
        GEN_CFG,
    )
    final_answer = strip_source_citations((result or "").strip())

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

    if not session_id:
        try:
            info = create_new_session(session.get("user") or "", title="Cuộc trò chuyện mới")
            session_id = info.get("session_id") or str(time.time())
        except Exception:
            session_id = str(time.time())

    add_message("user", user_text, session_id=session_id)

    bm25_folder = bm25_folder or DATA_DIR
    corpus_path = corpus_path or (FAISS_ALL_DIR / "corpus.jsonl")

    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model(
        bm25_folder=bm25_folder,
        corpus_path=corpus_path,
    )

    ctx = _load_ctx(session_id)
    history_msgs = _get_history_msgs_for_ctx()

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
        uploaded_files_meta = session.get("uploaded_files", [])
        session_doc_paths: List[str] = []

        if isinstance(uploaded_files_meta, list):
            for item in reversed(uploaded_files_meta):
                if isinstance(item, dict):
                    p = item.get("path")
                    if p and os.path.exists(p):
                        session_doc_paths = [p]
                        print(f"[RAG] Đã nhận diện file: {p}")
                        break

        if not session_doc_paths and isinstance(uploaded_files_meta, dict) and session_id in uploaded_files_meta:
            for item in reversed(uploaded_files_meta[session_id]):
                p = item.get("path")
                if p and os.path.exists(p):
                    session_doc_paths = [p]
                    print(f"[RAG] Đã nhận diện file từ dict: {p}")
                    break

        if isinstance(uploaded_files_meta, dict):
            uploaded_files_meta.pop(session_id, None)
            session["uploaded_files"] = uploaded_files_meta
        else:
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

        # ====== 3. Lấy file upload (tất cả file trong session) ======
    uploaded_files_meta = session.get("uploaded_files", [])

    session_doc_paths: List[str] = []
    seen_paths: set[str] = set()
    flat_metas: List[Dict[str, Any]] = []

    if isinstance(uploaded_files_meta, list):
        # danh sách metadata toàn session
        flat_metas = [m for m in uploaded_files_meta if isinstance(m, dict)]

        # build path list (lấy file mới nhất trước)
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
        # kiểu lưu theo session_id: {session_id: [meta...]}
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

    active_file_path: Optional[str] = session_doc_paths[0] if session_doc_paths else None
    active_source: Optional[str] = os.path.basename(active_file_path) if active_file_path else None

    is_generic_current = _is_generic_current_file_query(user_text)

    # 🔍 Xác định danh sách file (source) được nhắc tới trong câu hỏi
    focus_sources: Optional[List[str]] = None
    if flat_metas:
        focus_sources = _detect_focus_sources_from_query(user_text, flat_metas)

    # Nếu câu hỏi kiểu "file này" mà chỉ có 1 file -> mặc định focus file đó
    if not focus_sources and is_generic_current and len(session_doc_paths) == 1 and active_source:
        focus_sources = [active_source]

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
        timing = {}
    else:
        # 6. RAG: chọn SUBSET file dùng cho lượt này

        # Mặc định: dùng tất cả file trong session
        session_paths_for_rag = list(session_doc_paths)

        # Nếu user nhắc đích danh tên file -> chỉ dùng những file đó
        if focus_sources:
            allowed = set(focus_sources)
            session_paths_for_rag = [
                p for p in session_doc_paths
                if os.path.basename(p) in allowed
            ]

        # Nếu câu hỏi kiểu "file này", "2 file này" -> dùng N file mới nhất
        elif is_generic_current and session_doc_paths:
            lower_q = user_text.lower()
            n = 1  # mặc định 1 file

            # 1) Nếu user ghi rõ số: "2 file", "3 file"
            m = re.search(r'(\d+)\s*file', lower_q)
            if m:
                try:
                    n = int(m.group(1))
                except ValueError:
                    n = 1

            # 2) Nếu user ghi "hai file"
            elif "hai file" in lower_q:
                n = 2

            # 3) Nếu user dùng dạng số nhiều: "các file", "cac file", "những file", "nhung file"
            #    mà không ghi cụ thể bao nhiêu → mặc định là 2 file mới nhất
            elif (
                "các file" in lower_q
                or "cac file" in lower_q
                or "những file" in lower_q
                or "nhung file" in lower_q
            ):
                n = 2

            # Giới hạn trong [1, len(session_doc_paths)]
            n = max(1, min(n, len(session_doc_paths)))

            # Lấy n file mới nhất (do session_doc_paths đã build từ reversed(uploaded_files_meta))
            session_paths_for_rag = session_doc_paths[:n]

        only_use_session_docs = bool(session_paths_for_rag) and (
            is_generic_current or bool(focus_sources)
        )

        print(
            f"[RAG MODE] session_id={session_id} | all_files={len(session_doc_paths)} "
            f"| used_files={len(session_paths_for_rag)} "
            f"| only_use_session_docs={only_use_session_docs} "
            f"| active_source={active_source} | is_generic_current={is_generic_current} "
            f"| focus_sources={focus_sources}"
        )

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
        )

        ctx["last_branch"] = "rag_file_only" if only_use_session_docs else "rag"
        if session_doc_paths:
            ctx["last_docs"] = [os.path.basename(p) for p in session_doc_paths]


    add_message("assistant", final_answer, session_id=session_id)

    try:
        update_ctx(session_id, ctx)
    except Exception:
        pass

    try:
        history = get_history()
        user_count = len([m for m in history if m.get("role") == "user"])
        if user_count >= 7 and user_count % 7 == 0:
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
