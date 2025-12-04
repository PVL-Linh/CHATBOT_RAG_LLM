from __future__ import annotations
import json
import os
from langchain_core.documents import Document
from typing import Any, Dict, List, Optional
from langchain_community.vectorstores import FAISS
from app.Model_LLM.Chat_Database.redis_ctx import redis_client
from app.routes.image_ocr_utils import is_image_path
from .file_utils import _extract_text_from_uploaded_file, _summarize_uploaded_file, _split_text_to_chunks
from .utils_text import _is_internal_prompt_text

SESSION_DOC_VS: Dict[str, FAISS] = {}
SESSION_DOC_VS_META: Dict[str, Dict[str, float]] = {}
SESSION_DOC_SUMMARY: Dict[str, str] = {}

def _make_summary_key(session_id: str, path: str) -> str:
    basename = os.path.basename(path)
    try:
        mtime = int(os.path.getmtime(path))
    except Exception:
        mtime = 0
    return f"file_summary:{session_id}:{basename}:{mtime}"

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
