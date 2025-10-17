# -*- coding: utf-8 -*-
import json
from typing import List, Dict, Any, Tuple
from .gemini_client_hr import init_gemini, ask_gemini
from .utils_hr import clip

def _row_from_any(d: Any) -> Tuple[str, Any, str]:
    """
    Chuẩn hoá 1 phần tử nguồn thành (source, chunk_id, text).
    Hỗ trợ: dict trace chuẩn / LangChain Document / (Document, score) / list tương tự.
    """
    try:
        if isinstance(d, dict):
            return d.get("source"), d.get("chunk_id"), d.get("text") or ""
        # LangChain Document
        if hasattr(d, "metadata"):
            m = getattr(d, "metadata", {}) or {}
            txt = getattr(d, "page_content", "") or ""
            return m.get("source"), m.get("chunk_id"), txt
        # Tuple/list (Document, score) hoặc tương tự
        if isinstance(d, (list, tuple)) and d:
            first = d[0]
            if hasattr(first, "metadata"):
                m = first.metadata or {}
                txt = getattr(first, "page_content", "") or ""
                return m.get("source"), m.get("chunk_id"), txt
    except Exception:
        pass
    return (None, None, "")

def judge_answer(question: str, answer: str, docs: List[Dict[str, Any]], judge_model: str) -> dict:
    genai = init_gemini()

    rows = []
    for item in docs or []:
        src, cid, txt = _row_from_any(item)
        if (src or txt):
            rows.append(f"[{src}|{cid}] {clip(txt, 600)}")
    joined_sources = "\n\n".join(rows) if rows else "(no sources)"

    sys_prompt = (
        "Bạn là giám khảo RAG. Đánh giá câu trả lời dựa trên NGUỒN (danh sách các trích đoạn). "
        "Chấm điểm và GIẢI THÍCH ngắn gọn."
    )
    user_prompt = f"""
        QUESTION:
        {question}

        ANSWER:
        {answer}

        SOURCES (each block begins with [source|chunk_id]):
        {joined_sources}

        Return STRICT JSON with fields:
        - "relevance"
        - "groundedness"
        - "completeness"
        - "overall"
        - "notes": giải thích ngắn
        """.strip()

    raw = ask_gemini(genai, judge_model, sys_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw.strip().split("\n", 1)[-1])
        except Exception:
            return {"overall": None, "notes": f"Parse JSON failed. Raw: {clip(raw, 200)}"}
