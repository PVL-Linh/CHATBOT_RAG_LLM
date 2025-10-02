import json
from .gemini_client_hr import init_gemini, ask_gemini
from .utils_hr import clip
from typing import List, Dict, Any

def judge_answer(question: str, answer: str, docs: List[Dict[str, Any]], judge_model: str) -> dict:
    genai = init_gemini()
    joined_sources = "\n\n".join(f"[{d['source']}|{d['chunk_id']}] {clip(d.get('text'), 600)}" for d in docs)

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
- "relevance" (0-100)
- "groundedness" (0-100)
- "completeness" (0-100)
- "overall" (0-100)
- "notes": giải thích ngắn (<= 80 từ).
""".strip()

    raw = ask_gemini(genai, judge_model, sys_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw.strip().split("\n", 1)[-1])
        except Exception:
            return {"overall": None, "notes": f"Parse JSON failed. Raw: {clip(raw, 200)}"}
