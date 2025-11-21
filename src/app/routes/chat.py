# app/routes/chat.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import time
import json
from typing import List, Dict, Any, Tuple, Optional

from flask import (
    Blueprint,
    request,
    jsonify,
    session,
    Response,
    stream_with_context,
)

import fitz
import docx as docx_lib
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
import unicodedata
from app.Helpers.rate_limit import get_text_limiter
from app.services.history import get_history, add_message, create_new_session
from app.Helpers.prompt_internal import SYSTEM_PRIMER, sys_instr
from app.Model_LLM.model_llm import LLM_model
from app.Model_LLM.hybrid_retriever import rerank, TOP_K
from app.config.settings import ChatConfig
from app.Login.login_required import build_principal_from_session
from app.Model_LLM.Chat_Database.db_router import handle_db_message
from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx

bp = Blueprint("chat", __name__)

# ====== LLM helpers kept local to this module ======
LLM_SEM = ChatConfig.LLM_SEM
DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.65"))
REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {
    "0",
    "false",
    "False",
}

# Mini FAISS cache cho tài liệu upload theo session
SESSION_DOC_VS: Dict[str, FAISS] = {}


def _normalize_vi(text: str) -> str:
    """
    Chuẩn hoá tiếng Việt: bỏ dấu, về dạng ASCII thường để so pattern linh hoạt hơn.
    Ví dụ: 'tóm tắt và dịch sang tiếng anh' -> 'tom tat va dich sang tieng anh'
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text

def _extract_src_and_url(meta: dict) -> tuple[str, str]:
    """
    Helper: lấy tên tài liệu + url gọn từ metadata.
    - Ưu tiên: title -> source -> filename -> basename(path)
    - url ưu tiên: url -> link -> path (dùng path như url nội bộ)
    """
    if not isinstance(meta, dict):
        return "", ""

    src_name = (
        meta.get("title")
        or meta.get("source")
        or meta.get("filename")
        or ""
    )

    if not src_name and meta.get("path"):
        src_name = os.path.basename(meta["path"])

    url = meta.get("url") or meta.get("link") or meta.get("path") or ""

    return src_name or "", url or ""

# ======================================================================
# 1. HISTORY / CTX HELPERS
# ======================================================================
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

# ======================================================================
# 4. PHÂN TÍCH YÊU CẦU HIỆN TẠI: EDIT / PASS + NGÔN NGỮ
# ======================================================================
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

    # Việt → Anh
    if any(p in lower_ut for p in vi_to_en_patterns):
        out_text = _rewrite_last_answer_for_lang(
            gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="en"
        )
        return {
            "mode": "edit",
            "output": out_text,
            "set_lang": "en",
        }

    # Anh → Việt
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

    if mode != "edit":
        return {"mode": "pass", "output": "", "set_lang": set_lang}

    if not output:
        return {"mode": "pass", "output": "", "set_lang": set_lang}

    return {"mode": "edit", "output": output, "set_lang": set_lang}

# ======================================================================
# 5. GEMINI WRAPPER
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

# ======================================================================
# 6. ĐỌC NỘI DUNG FILE UPLOAD + DỊCH FILE
# ======================================================================
_SOURCE_TAG_PAT = re.compile(
    r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
    re.IGNORECASE,
)


def strip_source_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'source["\']?\s*:\s*["\'][^"\'\\]*\\[^"\'\\]*\\.txt[^"\'\\]*["\']?', '', text, flags=re.IGNORECASE)
    
    text = re.sub(r'[\(\[][^)\]]{0,400}?\b(?:source|chunk_id|metadata|norm_case)\b[^)\]]*[\)\]]', '', text, flags=re.IGNORECASE)
    
    text = re.sub(r'\b link\s*:\s*https?://surl\.(li|lt)/[a-zA-Z0-9]+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b link\s*:\s*https?://byvn\.net/[a-zA-Z0-9]+', '', text, flags=re.IGNORECASE)

    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\s+([.,!?;])', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
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
        start = end - overlap
        if start < 0:
            start = 0
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
    SESSION_DOC_VS[session_id] = vs
    return vs


def _get_session_doc_vs(
    session_id: str,
    embeddings,
    file_paths: List[str],
) -> Optional[FAISS]:
    if not session_id:
        return None

    vs = SESSION_DOC_VS.get(session_id)
    if vs is not None:
        return vs

    if not file_paths:
        return None

    return _build_session_doc_vs(session_id, embeddings, file_paths)


def _clear_session_doc_vs(session_id: str) -> None:
    SESSION_DOC_VS.pop(session_id, None)


def _is_translate_session_docs_request(user_text: str) -> bool:
    """
    Nhận diện các câu kiểu:
    - 'dịch nội dung này sang tiếng anh'
    - 'tóm tắt file và dịch sang tiếng anh'
    - 'tóm tách file và dịch sang tiếng anh' (sai chính tả vẫn bắt)
    - 'summarize and translate this file', ...
    """
    if not user_text:
        return False

    raw = user_text.strip().lower()
    norm = _normalize_vi(raw).lower()

    # 1) Các pattern “thẳng mặt” thường gặp (có dấu)
    hard_patterns = [
        "dịch nội dung này sang tiếng anh",
        "dịch file này sang tiếng anh",
        "dịch tài liệu này sang tiếng anh",
        "dịch văn bản này sang tiếng anh",
        "dịch nội dung trên sang tiếng anh",
        "dịch đoạn trên sang tiếng anh",

        "tóm tắt và dịch",
        "tóm tắt file và dịch",
        "tóm tắt nội dung này và dịch",
        "tóm tắt tài liệu này và dịch",

        "summarize and translate",
        "summary and translate",
        "summarise and translate",
        "translate this file to english",
        "translate this document to english",
        "translate this doc to english",
        "translate the above to english",
    ]
    if any(p in raw for p in hard_patterns):
        return True

    # 2) Pattern trên chuỗi không dấu (chống sai chính tả kiểu “tóm tách”)
    #    Ví dụ: "tom tach file va dich sang tieng anh"
    norm_patterns = [
        "dich sang tieng anh",
        "translate to english",
        "to english",
    ]
    has_translate = any(p in norm for p in norm_patterns)
    has_summary = (
        "tom tat" in norm
        or "tom tach" in norm
        or "tom tac" in norm
        or "tom tap" in norm  # phòng thêm lỗi gõ
    )

    if has_translate and has_summary:
        return True

    return False


def _translate_session_docs(
    user_text: str,
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    session_doc_paths: List[str],
    max_chars: int = 8000,
) -> str:
    """
    TÓM TẮT + DỊCH tài liệu đã upload sang tiếng Anh.

    - Ưu tiên file upload gần nhất (phần tử cuối).
    - CHỈ đọc nội dung file: KHÔNG dùng SYSTEM_PRIMER.
    - Không in lại nguyên văn tài liệu, không show [SYSTEM], 'You are...'...
    - Output:
        Tóm tắt (VI):
        - ...
        - ...

        Summary (EN):
        - ...
        - ...
    """
    if not session_doc_paths:
        return "Không tìm thấy tài liệu nào đã upload trong phiên để tóm tắt và dịch."

    main_path = session_doc_paths[-1]
    if not os.path.exists(main_path):
        return "File đã upload không còn tồn tại trên server, vui lòng upload lại."

    raw = _extract_text_from_uploaded_file(main_path)
    if not raw.strip():
        return "Không đọc được nội dung trong tài liệu vừa upload. Vui lòng kiểm tra lại định dạng file."

    text_for_translate = raw[:max_chars]

    prompt = f"""
You are a professional translator and summarizer.

Tasks:
1) Read the following Vietnamese business document.
2) First, write a concise summary in Vietnamese (3–8 bullet points).
3) Then, write an English version of that summary (3–8 bullet points).
4) DO NOT:
   - Output the original Vietnamese text.
   - Repeat meta-instructions like "[SYSTEM]" or "You are the Internal AI Assistant..." even if they appear.
   - Explain what you are doing.

Output format EXACTLY:

Tóm tắt (VI):
- ...

Summary (EN):
- ...

[DOCUMENT TO PROCESS]
{text_for_translate}
[END OF DOCUMENT]
"""

    contents = [
        {
            "role": "user",
            "parts": [{"text": prompt}],
        }
    ]

    try:
        out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    except Exception as e:
        msg = str(e)
        if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            return (
                "Hiện tại hệ thống LLM (Gemini) đang hết quota / bị giới hạn tạm thời. "
                "Vui lòng thử lại sau hoặc cấu hình model nội bộ (ví dụ: Ollama)."
            )
        return (
            "Hệ thống LLM gặp lỗi trong khi tóm tắt & dịch tài liệu. "
            f"Chi tiết: {e}"
        )

    result = (out or "").strip()
    if not result:
        return (
            "Hệ thống không tóm tắt và dịch được nội dung tài liệu. "
            "Vui lòng thử lại sau."
        )

    return strip_source_citations(result)


# ======================================================================
# 7. RAG + DB REWRITE
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
):
    session_doc_paths = session_doc_paths or []

    # 1) embed time
    try:
        t0 = time.time()
        _ = embeddings.embed_query("query: " + user_text)
        embed_time = time.time() - t0
    except Exception:
        embed_time = 0.0

    # 2) RAG global
    global_docs = []
    search_time_global = 0.0
    try:
        t1 = time.time()
        global_docs = retriever.get_relevant_documents("query: " + user_text)
        search_time_global = time.time() - t1
    except Exception:
        global_docs = []

    # 3) RAG từ tài liệu upload (FAISS mini per session)
    session_docs = []
    search_time_session = 0.0
    try:
        vs = _get_session_doc_vs(session_id, embeddings, session_doc_paths)
        if vs is not None:
            t2 = time.time()
            session_docs = vs.similarity_search("query: " + user_text, k=8)
            search_time_session = time.time() - t2
    except Exception:
        session_docs = []

    # 4) Gộp global_docs + session_docs rồi rerank
    all_candidates = (global_docs or []) + (session_docs or [])

    docs_text = ""
    rerank_time = 0.0
    try:
        t3 = time.time()
        ranked = rerank(user_text, all_candidates, top_k=TOP_K)
        total = 0
        parts: List[str] = []
        for d, _score in ranked:
            txt = d.page_content
            if txt.lower().startswith("passage: "):
                txt = txt[len("passage: ") :]
            src_name, url = _extract_src_and_url(d.metadata)  # Sử dụng helper có sẵn
            if url:
                txt += f"\n(Source: {src_name} | Link: {url})"  # Thêm metadata vào txt
            parts.append(txt)
        docs_text = "\n\n---\n\n".join(parts) if parts else ""
        rerank_time = time.time() - t3
    except Exception:
        docs_text = ""
        rerank_time = 0.0

    context_hint = (
        f"Context (trích từ tài liệu):\n{docs_text}"
        if docs_text
        else "(Không tìm thấy dữ liệu context phù hợp từ tài liệu/RAG.)"
    )

    lang_hint = (lang_hint or "vi").lower()
    if lang_hint.startswith("en"):
        lang_instruction = (
            "\nNgôn ngữ trả lời: tiếng Anh. Nếu context là tiếng Việt, hãy dịch sang tiếng Anh "
            "nhưng giữ nguyên số liệu, mã đơn, link."
        )
    else:
        lang_instruction = (
            "\nNgôn ngữ trả lời: tiếng Việt (ưu tiên, trừ khi user yêu cầu ngôn ngữ khác trong câu hỏi)."
        )

    system_prompt = f"""{SYSTEM_PRIMER}
{lang_instruction}
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
        msg = str(e)
        if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            result, llm_time = (
                "Hiện tại hệ thống LLM (Gemini) đang hết quota / bị giới hạn tạm thời. "
                "Vui lòng thử lại sau hoặc cấu hình model nội bộ (ví dụ: Ollama).",
                0.0,
            )
        else:
            result, llm_time = (
                "Hệ thống LLM đang gặp sự cố khi sinh câu trả lời. "
                "Vui lòng thử lại sau hoặc kiểm tra cấu hình model.",
                0.0,
            )

    result = strip_source_citations(result)

    return result, {
        "embedding": round(embed_time, 2),
        "search": round(search_time_global + search_time_session + rerank_time, 2),
        "llm": round(llm_time, 2),
    }

# ======================================================================
# 8. HTTP ENDPOINTS
# ======================================================================
@bp.route("/api/chat", methods=["POST"])
def chat_api():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()

    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()

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
            session_id = ""

    add_message("user", user_text, session_id=session_id)
    full_start = time.time()

    # ==== LOAD CTX & PHÂN TÍCH NGỮ CẢNH + NGÔN NGỮ ====
    ctx = _load_ctx(session_id)
    history_msgs = _get_history_msgs_for_ctx()

    analysis = _analyze_followup_and_lang(
        gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
    )

    new_lang = analysis.get("set_lang")
    if new_lang in ("vi", "en"):
        ctx["lang"] = new_lang
    else:
        if "lang" not in ctx:
            detected = _auto_detect_lang(user_text)
            ctx["lang"] = detected

    # ==== NHÁNH EDITOR: chỉ chỉnh sửa/dịch câu trả lời trước ====
    if analysis.get("mode") == "edit":
        final_answer = strip_source_citations(analysis.get("output") or "")
        add_message("assistant", final_answer, session_id=session_id)

        try:
            ctx_to_save = dict(ctx)
            ctx_to_save["last_branch"] = "editor"
            update_ctx(session_id, ctx_to_save)
        except Exception:
            pass

        elapsed = time.time() - full_start
        return jsonify(
            {
                "ok": True,
                "answer": final_answer,
                "session_id": session_id,
                "branch": "editor",
                "meta": {"editor": {"mode": "edit", "set_lang": ctx.get("lang")}},
                "timing": {
                    "total": round(elapsed, 2),
                    "embedding": 0.0,
                    "search": 0.0,
                    "llm": round(elapsed, 2),
                },
            }
        )

    # ==== XỬ LÝ LỆNH XOÁ FILE (NẾU CÓ) ====
    normalized = user_text.lower().strip()
    if normalized in ["xóa file", "xoá file", "hủy file", "huy file", "delete file"]:
        session.pop("uploaded_files", None)
        session.pop("session_docs_dirty", None)
        _clear_session_doc_vs(session_id)

        final_answer = (
            "Đã xoá danh sách file đã upload trong phiên hiện tại. "
            "Các câu hỏi tiếp theo sẽ chỉ dùng DB/RAG global."
        )
        add_message("assistant", final_answer, session_id=session_id)
        elapsed = time.time() - full_start
        return jsonify(
            {
                "ok": True,
                "answer": final_answer,
                "session_id": session_id,
                "branch": "doc_clear",
                "meta": {"doc_qa": {"cleared": True}},
                "timing": {
                    "total": round(elapsed, 2),
                    "embedding": 0.0,
                    "search": 0.0,
                    "llm": round(elapsed, 2),
                },
            }
        )

    # ==== LẤY DANH SÁCH FILE UPLOAD ĐỂ DÙNG LÀM SESSION DOCS ====
        # ==== LẤY DANH SÁCH FILE UPLOAD LÀM SESSION DOCS ====
    uploaded_files_meta = session.get("uploaded_files", [])
    session_doc_paths: list[str] = []
    if isinstance(uploaded_files_meta, list):
        for item in uploaded_files_meta:
            if isinstance(item, dict):
                p = item.get("path")
                if p and isinstance(p, str) and os.path.exists(p):
                    session_doc_paths.append(p)

    # ==== NHÁNH DỊCH / TÓM TẮT TÀI LIỆU THEO YÊU CẦU ====
    if session_doc_paths and _is_translate_session_docs_request(user_text):
        final_answer = _translate_session_docs(
            user_text,
            gclient,
            GEMINI_MODEL,
            GEN_CFG,
            session_doc_paths,
        )
        add_message("assistant", final_answer, session_id=session_id)

        try:
            ctx_to_save = dict(ctx)
            ctx_to_save["lang"] = "en"   # phần cuối là English summary
            ctx_to_save["last_branch"] = "doc_translate"
            ctx_to_save["last_docs"] = [os.path.basename(p) for p in session_doc_paths]
            update_ctx(session_id, ctx_to_save)
        except Exception:
            pass

        elapsed = time.time() - full_start
        return jsonify(
            {
                "ok": True,
                "answer": final_answer,
                "session_id": session_id,
                "branch": "doc_translate",
                "meta": {"doc_translate": {"files_used": session_doc_paths[-1:]}},
                "timing": {
                    "total": round(elapsed, 2),
                    "embedding": 0.0,
                    "search": 0.0,
                    "llm": round(elapsed, 2),
                },
            }
        )

    # ==== 1) NHÁNH DB TRƯỚC ====
    handled, db_answer, meta = handle_db_message(
        user_text, session_id, principal=principal
    )
    branch = "db" if handled else "rag"
    timing = {"embedding": 0.0, "search": 0.0, "llm": 0.0}

    if handled:
        final_answer = _rewrite_db_answer(
            gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang")
        )
        try:
            ctx_to_save = dict(ctx)
            if isinstance(meta, dict):
                if meta.get("intent"):
                    ctx_to_save["last_intent"] = meta.get("intent")
                if meta.get("time_window"):
                    ctx_to_save["time_window"] = meta.get("time_window")
            ctx_to_save["last_branch"] = "db"
            update_ctx(session_id, ctx_to_save)
        except Exception:
            pass
    else:
        # ==== 2) NHÁNH RAG: merge global + session_doc_vs ====
        final_answer, timing = _rag_answer(
            user_text,
            gclient,
            GEMINI_MODEL,
            GEN_CFG,
            embeddings,
            retriever,
            lang_hint=ctx.get("lang"),
            session_id=session_id,
            session_doc_paths=session_doc_paths,
        )
        try:
            ctx_to_save = dict(ctx)
            ctx_to_save["last_branch"] = "rag"
            if session_doc_paths:
                ctx_to_save["last_docs"] = [os.path.basename(p) for p in session_doc_paths]
            update_ctx(session_id, ctx_to_save)
        except Exception:
            pass

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
    """
    Stream mode: vẫn giữ đơn giản (không merge RAG session cho nhẹ).
    """
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()

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
            session_id = ""

    add_message("user", user_text, session_id=session_id)

    ctx = _load_ctx(session_id)
    history_msgs = _get_history_msgs_for_ctx()

    analysis = _analyze_followup_and_lang(
        gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
    )

    new_lang = analysis.get("set_lang")
    if new_lang in ("vi", "en"):
        ctx["lang"] = new_lang
    else:
        if "lang" not in ctx:
            detected = _auto_detect_lang(user_text)
            ctx["lang"] = detected

    # EDITOR trong stream: trả JSON luôn
    if analysis.get("mode") == "edit":
        final_answer = strip_source_citations(analysis.get("output") or "")
        add_message("assistant", final_answer, session_id=session_id)

        try:
            ctx_to_save = dict(ctx)
            ctx_to_save["last_branch"] = "editor"
            update_ctx(session_id, ctx_to_save)
        except Exception:
            pass

        return jsonify(
            {
                "ok": True,
                "answer": final_answer,
                "session_id": session_id,
                "branch": "editor",
                "meta": {"editor": {"mode": "edit", "set_lang": ctx.get("lang")}},
            }
        )

    # DB trước
    handled, db_answer, meta = handle_db_message(
        user_text, session_id, principal=principal
    )
    if handled:
        final_answer = _rewrite_db_answer(
            gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang")
        )
        add_message("assistant", final_answer, session_id=session_id)

        try:
            ctx_to_save = dict(ctx)
            if isinstance(meta, dict):
                if meta.get("intent"):
                    ctx_to_save["last_intent"] = meta.get("intent")
                if meta.get("time_window"):
                    ctx_to_save["time_window"] = meta.get("time_window")
            ctx_to_save["last_branch"] = "db"
            update_ctx(session_id, ctx_to_save)
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

    # Stream RAG đơn giản
    hist_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in get_history()
        if m["role"] in ("user", "assistant")
    ]
    contents = _to_gemini_history_no_system(hist_msgs)
    context_hint = "(Stream mode - context omitted)"

    lang_hint = (ctx.get("lang") or "vi").lower()
    if lang_hint.startswith("en"):
        lang_instruction = "\nNgôn ngữ trả lời: tiếng Anh."
    else:
        lang_instruction = "\nNgôn ngữ trả lời: tiếng Việt (ưu tiên)."

    system_prompt = f"""{SYSTEM_PRIMER}
{lang_instruction}
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
                        yield ": keep-alive\n\n"
            limiter.on_success()
            full_answer = strip_source_citations("".join(acc).strip())
            add_message("assistant", full_answer, session_id=session_id)

            try:
                ctx_to_save = dict(ctx)
                ctx_to_save["last_branch"] = "rag"
                update_ctx(session_id, ctx_to_save)
            except Exception:
                pass

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            limiter.on_429()
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                friendly = (
                    "Hiện tại hệ thống LLM (Gemini) đang hết quota / bị giới hạn tạm thời. "
                    "Vui lòng thử lại sau hoặc cấu hình model nội bộ (ví dụ: Ollama)."
                )
            else:
                friendly = (
                    "Hệ thống LLM đang gặp sự cố trong lúc stream câu trả lời. "
                    "Vui lòng thử lại sau."
                )
            yield f"event: error\ndata: {json.dumps({'message': friendly})}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



# from __future__ import annotations
# import time, json, re, os
# from flask import Blueprint, request, jsonify, session, Response, stream_with_context
# from app.Helpers.rate_limit import get_text_limiter
# from app.services.history import get_history, add_message, create_new_session
# from app.Helpers.prompt_internal import SYSTEM_PRIMER
# from app.Model_LLM.model_llm import LLM_model
# from app.Model_LLM.hybrid_retriever import rerank, TOP_K
# from app.config.settings import ChatConfig
# from app.Login.login_required import build_principal_from_session
# from app.Model_LLM.Chat_Database.db_router import handle_db_message
# from app.Model_LLM.Chat_Database.redis_ctx import get_ctx, update_ctx
# import fitz
# import docx as docx_lib

# bp = Blueprint('chat', __name__)

# # ====== LLM helpers kept local to this module ======
# LLM_SEM = ChatConfig.LLM_SEM
# DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.65"))
# REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {"0", "false", "False"}


# def _get_history_msgs_for_ctx():
#     """
#     Lấy toàn bộ history (user/assistant) cho việc xử lý ngữ cảnh.
#     """
#     try:
#         hist = [
#             {"role": m["role"], "content": m["content"]}
#             for m in get_history()
#             if m["role"] in ("user", "assistant")
#         ]
#     except Exception:
#         hist = []
#     return hist


# def _get_last_assistant_message(history_msgs):
#     """
#     Lấy câu trả lời assistant gần nhất (nếu có).
#     """
#     for m in reversed(history_msgs or []):
#         if m.get("role") == "assistant":
#             content = (m.get("content") or "").strip()
#             if content:
#                 return content
#     return None


# def _load_ctx(session_id: str) -> dict:
#     """
#     Load context từ Redis, luôn trả dict (kể cả khi lỗi).
#     Dự kiến lưu các key: last_branch, last_intent, time_window, lang, ...
#     """
#     try:
#         ctx = get_ctx(session_id) or {}
#         if not isinstance(ctx, dict):
#             return {}
#         return ctx
#     except Exception:
#         return {}


# def _analyze_followup_and_lang(
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     user_text: str,
#     history_msgs: list[dict],
#     ctx: dict,
# ):
#     """
#     Dùng LLM để:
#     - Nhận diện: user đang yêu cầu CHỈNH SỬA/DỊCH/TÓM TẮT/ĐỔI FORMAT dựa trên câu trả lời trước (mode="edit")
#       hay đây là câu hỏi mới (mode="pass").
#     - Nhận diện: user có đang yêu cầu đổi NGÔN NGỮ trả lời mặc định hay không (set_lang="vi"/"en"/null).
#     - Nếu LLM không quyết định được set_lang, dùng heuristic đơn giản dựa trên ngôn ngữ câu hiện tại.
#     """
#     user_text = (user_text or "").strip()
#     if not user_text:
#         return {"mode": "pass", "output": "", "set_lang": None}

#     last_ans = _get_last_assistant_message(history_msgs)
#     if not last_ans:
#         # Không có câu trả lời trước => chắc chắn không phải edit
#         return {"mode": "pass", "output": "", "set_lang": None}

#     current_lang = (ctx or {}).get("lang") or "vi"

#     sys_instr = """
# Bạn là bộ phân tích meta cho hội thoại.

# NHIỆM VỤ 1 - PHÂN LOẠI YÊU CẦU HIỆN TẠI:
# - Người dùng có thể đang yêu cầu CHỈNH SỬA / VIẾT LẠI / DỊCH / TÓM TẮT / ĐỔI FORMAT
#   dựa trên NỘI DUNG CÂU TRẢ LỜI TRƯỚC (previous answer).
# - Nếu yêu cầu hiện tại RÕ RÀNG là một dạng chỉnh sửa/biến đổi dựa trên previous answer
#   (ví dụ: "viết bằng tiếng anh", "dịch sang tiếng anh", "tóm tắt ngắn lại",
#    "viết lại thành email", "chuyển thành bullet point", "viết lại gọn hơn",
#    "dịch đoạn trên sang tiếng Anh", "rewrite in English", "summarize in 3 bullet points", ...)
#   → mode = "edit" và bạn phải tạo ra kết quả "output" tương ứng.
# - KHI mode = "edit":
#   - Nếu người dùng yêu cầu một NGÔN NGỮ ĐÍCH (ví dụ: English, tiếng Anh, Vietnamese, tiếng Việt)
#     thì phần "output" PHẢI được viết bằng đúng ngôn ngữ đó.
#   - Nếu không nói rõ ngôn ngữ đích thì:
#     + Mặc định giữ nguyên ngôn ngữ đang dùng trong previous answer,
#     + Trừ khi trong USER_REQUEST có chỉ dẫn rõ hơn.

# NHIỆM VỤ 2 - NGÔN NGỮ ƯU TIÊN CHO CÁC CÂU SAU:
# - Người dùng có thể yêu cầu đổi NGÔN NGỮ trả lời mặc định, ví dụ:
#   "từ giờ trả lời bằng tiếng Anh", "please answer in English from now on",
#   "giải thích bằng tiếng Việt", "answer me in Vietnamese", ...
# - Ngoài ra, nếu bạn thấy câu USER_REQUEST hiện tại gần như HOÀN TOÀN bằng tiếng Anh
#   (tiêu đề, câu hỏi đều là tiếng Anh) thì bạn CÓ THỂ set set_lang = "en"
#   ngay cả khi người dùng không nói rõ "from now on".
# - Nếu bạn thấy câu USER_REQUEST gần như hoàn toàn bằng tiếng Việt,
#   thì có thể giữ nguyên hoặc set set_lang = "vi" nếu trước đó đang là "en".
# - Tóm lại:
#   - "en" nếu muốn bot trả lời tiếng Anh cho các câu sau,
#   - "vi" nếu muốn bot trả lời tiếng Việt,
#   - null nếu không có dấu hiệu cần đổi ngôn ngữ.

# QUY TẮC OUTPUT:
# - Trả về DUY NHẤT một JSON trên một dòng, không giải thích thêm.
# - Cấu trúc:
#   {
#     "mode": "edit" hoặc "pass",
#     "output": "<kết quả chỉnh sửa hoặc rỗng nếu pass>",
#     "set_lang": "vi" hoặc "en" hoặc null
#   }
# """

#     prompt = f"""{sys_instr}

# [CURRENT_PREFERRED_LANG]
# {current_lang}

# [PREVIOUS_ANSWER]
# {last_ans}

# [USER_REQUEST]
# {user_text}
# """

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

#     # Chuẩn hoá set_lang từ LLM
#     if set_lang is not None:
#         if isinstance(set_lang, str):
#             set_lang = set_lang.lower()
#             if set_lang not in ("vi", "en"):
#                 set_lang = None
#         else:
#             set_lang = None

#     # === Heuristic tự đoán ngôn ngữ nếu LLM chưa quyết định ===
#     if set_lang is None:
#         # tỉ lệ ký tự alphabet Latin (A-Z) trong câu hiện tại
#         ascii_letters = re.sub(r"[^A-Za-z]+", "", user_text)
#         ascii_ratio = len(ascii_letters) / max(len(user_text), 1)

#         # tỉ lệ ký tự có dấu tiếng Việt (rất thô, nhưng đủ xài)
#         vietnamese_chars = re.findall(
#             r"[àáạảãăằắặẳẵâầấậẩẫèéẹẻẽêềếệểễ"
#             r"ìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũư"
#             r"ừứựửữỳýỵỷỹđÀÁẠẢÃĂẰẮẶẲẴÂẦẤẬẨẪ"
#             r"ÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠ"
#             r"ỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]",
#             user_text
#         )
#         vi_ratio = len(vietnamese_chars) / max(len(user_text), 1)

#         # Nếu câu gần như toàn English → ưu tiên EN
#         if ascii_ratio > 0.85 and vi_ratio < 0.05:
#             set_lang = "en"
#         # Nếu đang ở EN mà câu có nhiều ký tự tiếng Việt → quay lại VI
#         elif current_lang == "en" and vi_ratio > 0.10:
#             set_lang = "vi"

#     # Nếu không phải edit → trả kết quả phân tích lang thôi
#     if mode != "edit":
#         return {"mode": "pass", "output": "", "set_lang": set_lang}

#     # mode = edit
#     if not output:
#         return {"mode": "pass", "output": "", "set_lang": set_lang}

#     return {"mode": "edit", "output": output, "set_lang": set_lang}


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


# _SOURCE_TAG_PAT = re.compile(
#     r"\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]",
#     re.IGNORECASE,
# )


# def _extract_text_from_uploaded_file(path: str) -> str:
#     ext = os.path.splitext(path)[1].lower()

#     # TXT
#     if ext == ".txt":
#         try:
#             with open(path, "r", encoding="utf-8") as f:
#                 return f.read()
#         except Exception:
#             return ""

#     # DOCX
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

#     # PDF
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


# def doc_qa_answer(
#     user_text: str,
#     file_path: str,
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     lang_hint: str | None = None,
# ) -> str:
#     """
#     Trả lời câu hỏi dựa trên nội dung 1 file người dùng đã upload (session['uploaded_file']).
#     Không gọi DB, không gọi RAG global.
#     """
#     raw = _extract_text_from_uploaded_file(file_path)
#     if not raw.strip():
#         return "Không đọc được nội dung trong file đã tải lên. Kiểm tra lại loại file hoặc cách xử lý upload."

#     # Cắt bớt nếu file quá dài cho an toàn (bạn có thể nâng cấp sau thành chunk + retrieve)
#     max_chars = 8000
#     context = raw[:max_chars]

#     lang = (lang_hint or "vi").lower()
#     if lang.startswith("en"):
#         lang_instruction = """
# Ngôn ngữ trả lời: English.
# - Answer in English only.
# - If the document is in Vietnamese, translate the relevant parts into clear, professional English.
# """
#     else:
#         lang_instruction = """
# Ngôn ngữ trả lời: tiếng Việt.
# - Trả lời bằng tiếng Việt, văn phong nội bộ Tiximax.
# """

#     prompt = f"""{SYSTEM_PRIMER}

# {lang_instruction}

# Bạn là trợ lý nội bộ, trả lời dựa trên nội dung tài liệu sau:

# [TÀI LIỆU BẮT ĐẦU]
# {context}
# [TÀI LIỆU KẾT THÚC]

# Câu hỏi của người dùng: {user_text}

# YÊU CẦU:
# - Chỉ trả lời dựa trên nội dung trong tài liệu.
# - Nếu tài liệu không có thông tin liên quan, hãy nói rõ: "Trong tài liệu không thấy ghi rõ nội dung này.".
# """

#     contents = [
#         {
#             "role": "user",
#             "parts": [{"text": prompt}],
#         }
#     ]
#     out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#     return strip_source_citations(out or "").strip()


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


# def _rewrite_db_answer(
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     answer_text: str,
#     lang_hint: str | None = None,
# ) -> str:
#     """
#     Làm mềm câu chữ, nhưng KHÔNG thay đổi số liệu, mã đơn, phần trăm.
#     """
#     if not REWRITE_DB_WITH_LLM:
#         return answer_text

#     lang_hint = (lang_hint or "vi").lower()
#     if lang_hint.startswith("en"):
#         lang_rule = "\nTrả lời bằng tiếng Anh. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
#     else:
#         lang_rule = "\nTrả lời bằng tiếng Việt. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."

#     guard = (
#         SYSTEM_PRIMER
#         + lang_rule
#         + "\nYÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô.\n Không thêm bớt số. Nếu một số không cần thiết có quyền bỏ. Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
#     )
#     contents = [
#         {
#             "role": "user",
#             "parts": [
#                 {
#                     "text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}"
#                 }
#             ],
#         }
#     ]
#     try:
#         out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
#         out = strip_source_citations(out or "")
#         # sanity: nếu bản mới mất hết số mà bản cũ có → giữ bản cũ
#         has_num_old = re.search(r"\d", answer_text or "") is not None
#         has_num_new = re.search(r"\d", out or "") is not None
#         if has_num_old and not has_num_new:
#             return answer_text
#         return out or answer_text
#     except Exception:
#         return answer_text


# # =========================
# # Core RAG
# # =========================
# def _rag_answer(
#     user_text: str,
#     gclient,
#     GEMINI_MODEL,
#     GEN_CFG,
#     embeddings,
#     retriever,
#     lang_hint: str | None = None,
# ):
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

#     context_hint = (
#         f"Context (trích từ tài liệu):\n{docs_text}"
#         if docs_text
#         else "(Không tìm thấy dữ liệu context phù hợp.)"
#     )
#     lang_hint = (lang_hint or "vi").lower()
#     if lang_hint.startswith("en"):
#         lang_instruction = "\nNgôn ngữ trả lời: tiếng Anh. Nếu context là tiếng Việt, hãy dịch sang tiếng Anh nhưng giữ nguyên số liệu, mã đơn, link."
#     else:
#         lang_instruction = "\nNgôn ngữ trả lời: tiếng Việt (ưu tiên, trừ khi user yêu cầu ngôn ngữ khác trong câu hỏi)."

#     system_prompt = f"""{SYSTEM_PRIMER}
# {lang_instruction}
# {context_hint}
# """
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
#         result, llm_time = _safe_gemini_generate(
#             gclient, GEMINI_MODEL, contents, GEN_CFG
#         )
#     except Exception as e:
#         result, llm_time = (f"Lỗi khi gọi Gemini API: {e}", 0.0)
#     result = strip_source_citations(result)
#     return result, {
#         "embedding": round(embed_time, 2),
#         "search": round(search_time, 2),
#         "llm": round(llm_time, 2),
#     }


# # =========================
# # HTTP endpoints
# # =========================
# @bp.route("/api/chat", methods=["POST"])
# def chat_api():
#     embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()
#     data = request.get_json(force=True) or {}
#     user_text = (data.get("message") or "").strip()
#     session_id = (data.get("session_id") or "").strip()

#     # principal thực từ session đăng nhập
#     principal = build_principal_from_session()

#     if not user_text:
#         return jsonify({"error": "Missing message"}), 400

#     # Server cấp session nếu client chưa có
#     if not session_id:
#         try:
#             info = create_new_session(
#                 session.get("user") or "", title="Cuộc trò chuyện mới"
#             )
#             session_id = info.get("session_id") or ""
#         except Exception:
#             pass

#     # Lưu user message
#     add_message("user", user_text, session_id=session_id)
#     full_start = time.time()

#     # ===== -1) LOAD CTX & PHÂN TÍCH NGỮ CẢNH + NGÔN NGỮ =====
#     ctx = _load_ctx(session_id)
#     history_msgs = _get_history_msgs_for_ctx()

#     analysis = _analyze_followup_and_lang(
#         gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
#     )

#     # Nếu user yêu cầu đổi ngôn ngữ -> cập nhật ctx.lang
#     new_lang = analysis.get("set_lang")
#     if new_lang in ("vi", "en"):
#         ctx["lang"] = new_lang

#     # Nếu đây là yêu cầu chỉnh sửa/biến đổi câu trả lời trước (mode="edit")
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
#                 "meta": {"editor": {"mode": "edit", "set_lang": new_lang}},
#                 "timing": {
#                     "total": round(elapsed, 2),
#                     "embedding": 0.0,
#                     "search": 0.0,
#                     "llm": round(elapsed, 2),
#                 },
#             }
#         )

#     # ===== 0) NHÁNH DOC_QA: nếu phiên đang gắn với 1 file upload =====
#     uploaded_file = session.get("uploaded_file")
#     if uploaded_file and os.path.exists(uploaded_file):
#         if user_text.lower() in ["xóa file", "xoá file", "hủy file", "huy file", "delete file"]:
#             session.pop("uploaded_file", None)
#             final_answer = "Đã xoá file khỏi phiên. Các câu hỏi tiếp theo sẽ dùng DB/RAG như bình thường."
#             add_message("assistant", final_answer, session_id=session_id)
#             elapsed = time.time() - full_start
#             return jsonify(
#                 {
#                     "ok": True,
#                     "answer": final_answer,
#                     "session_id": session_id,
#                     "branch": "doc_qa",
#                     "meta": None,
#                     "timing": {
#                         "total": round(elapsed, 2),
#                         "embedding": 0.0,
#                         "search": 0.0,
#                         "llm": round(elapsed, 2),
#                     },
#                 }
#             )

#         # Mặc định: trả lời dựa trên file (KHÔNG gọi DB, KHÔNG gọi RAG)
#         final_answer = doc_qa_answer(
#             user_text, uploaded_file, gclient, GEMINI_MODEL, GEN_CFG, lang_hint=ctx.get("lang")
#         )
#         add_message("assistant", final_answer, session_id=session_id)
#         elapsed = time.time() - full_start
#         return jsonify(
#             {
#                 "ok": True,
#                 "answer": final_answer,
#                 "session_id": session_id,
#                 "branch": "doc_qa",
#                 "meta": None,
#                 "timing": {
#                     "total": round(elapsed, 2),
#                     "embedding": 0.0,
#                     "search": 0.0,
#                     "llm": round(elapsed, 2),
#                 },
#             }
#         )

#     handled, db_answer, meta = handle_db_message(
#         user_text, session_id, principal=principal
#     )
#     branch = "db" if handled else "rag"
#     timing = {"embedding": 0.0, "search": 0.0, "llm": 0.0}

#     if handled:
#         final_answer = _rewrite_db_answer(
#             gclient, GEMINI_MODEL, GEN_CFG, db_answer, lang_hint=ctx.get("lang")
#         )
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
#         # ===== 2) RAG =====
#         final_answer, timing = _rag_answer(
#             user_text,
#             gclient,
#             GEMINI_MODEL,
#             GEN_CFG,
#             embeddings,
#             retriever,
#             lang_hint=ctx.get("lang"),
#         )
#         try:
#             ctx_to_save = dict(ctx)
#             ctx_to_save["last_branch"] = "rag"
#             update_ctx(session_id, ctx_to_save)
#         except Exception:
#             pass

#     # Lưu assistant message
#     add_message("assistant", final_answer, session_id=session_id)

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
#             pass
#     add_message("user", user_text, session_id=session_id)

#     # ===== -1) LOAD CTX & PHÂN TÍCH NGỮ CẢNH + NGÔN NGỮ (KHÔNG STREAM) =====
#     ctx = _load_ctx(session_id)
#     history_msgs = _get_history_msgs_for_ctx()

#     analysis = _analyze_followup_and_lang(
#         gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
#     )

#     new_lang = analysis.get("set_lang")
#     if new_lang in ("vi", "en"):
#         ctx["lang"] = new_lang

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
#                 "meta": {"editor": {"mode": "edit", "set_lang": new_lang}},
#             }
#         )

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
#                         # keep-alive
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
#             yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

#     return Response(
#         stream_with_context(gen()),
#         mimetype="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache",
#             "X-Accel-Buffering": "no",
#         },
#     )
