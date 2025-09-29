import time
from typing import Tuple, List, Dict, Any
from langchain_core.documents import Document

from .config_hr import (
    TOP_K, K_SEM, K_LEX, MAX_CHARS_CTX, ENABLE_JUDGE, GEMINI_MODEL_ANSWER, GEMINI_MODEL_JUDGE,
    METRICS, CONTINUE_RETRIEVE
)
from .faiss_store_hr import load_faiss_vs
from .hybrid_hr import hybrid_retrieve
from .rerank_hr import rerank
from .context_hr import build_context
from .gemini_client_hr import init_gemini, ask_gemini
from .prompts_hr import get_system_prompt
from .judge_hr import judge_answer as _judge
from .utils_hr import clip

_LAST: Dict[str, Any] = {"question": "", "answer": "", "trace": []}

def answer_with_rag(question: str) -> Tuple[str, List[Dict[str, Any]]]:
    vs = load_faiss_vs()

    # 1) Hybrid retrieve
    t0 = time.time()
    docs = hybrid_retrieve(vs, question, k_sem=K_SEM, k_lex=K_LEX, top_k=TOP_K)
    t1 = time.time()

    # 2) (Optional) rerank
    ranked = rerank(question, docs, top_k=TOP_K)
    t2 = time.time()

    # 3) Build context + trace
    ctx = build_context(ranked, max_chars=MAX_CHARS_CTX)
    trace: List[Dict[str, Any]] = []
    for d, score in ranked:
        m = d.metadata or {}
        trace.append({
            "source": m.get("source", "?"),
            "chunk_id": m.get("chunk_id", -1),
            "score": float(score) if score is not None else None,
            "text": d.page_content,
        })
    t3 = time.time()

    # 4) Ask Gemini
    genai = init_gemini()
    sys_prompt = get_system_prompt(for_continue=False)
    user_prompt = f"""
Câu hỏi: {question}

Ngữ cảnh (mỗi đoạn kèm thẻ [source|chunk_id]):
{ctx}

Yêu cầu:
1) Trả lời bằng tiếng Việt.
2) Chỉ dùng thông tin từ NGỮ CẢNH. Không bịa.
3) Khi dẫn chứng, gắn thẻ [source|chunk_id] ngay sau câu/ý tương ứng.
""".strip()

    t4 = time.time()
    answer = ask_gemini(genai, GEMINI_MODEL_ANSWER, sys_prompt, user_prompt, json_mode=False)
    t5 = time.time()

    if METRICS:
        print(
            "[METRIC] t_retrieve={:.3f}s | t_rerank={:.3f}s | t_build={:.3f}s | t_llm={:.3f}s | t_total={:.3f}s".format(
                (t1 - t0), (t2 - t1), (t3 - t2), (t5 - t4), (t5 - t0)
            )
        )

    _LAST["question"], _LAST["answer"], _LAST["trace"] = question, answer, trace
    return answer, trace

def continue_with_last(followup_text: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    if not _LAST.get("trace"):
        raise RuntimeError("Không có ngữ cảnh trước để 'viết tiếp'. Hãy hỏi một câu trước.")

    vs = load_faiss_vs()

    # Optionally re-retrieve để mở rộng
    if CONTINUE_RETRIEVE:
        combined_q = f"{_LAST.get('question','')} {followup_text}".strip()
        docs = hybrid_retrieve(vs, combined_q, k_sem=K_SEM, k_lex=K_LEX, top_k=TOP_K)
        ranked = rerank(combined_q, docs, top_k=TOP_K)
    else:
        ranked = []
        for d in _LAST["trace"]:
            doc = Document(page_content=d["text"], metadata={"source": d["source"], "chunk_id": d["chunk_id"]})
            ranked.append((doc, d.get("score")))

    ctx = build_context(ranked, max_chars=MAX_CHARS_CTX)

    genai = init_gemini()
    sys_prompt = get_system_prompt(for_continue=True)

    prev = clip(_LAST.get("answer", ""), 1500)
    user_prompt = f"""
Phần trả lời trước (rút gọn):
{prev}

Yêu cầu viết tiếp / hướng dẫn thêm từ người dùng:
{followup_text or '(không có)'}

Ngữ cảnh (mỗi đoạn kèm thẻ [source|chunk_id]):
{ctx}

Yêu cầu:
- Viết tiếp mạch nội dung ở trên, tránh lặp lại. Chỉ dùng thông tin có trong Ngữ cảnh.
- Giữ chuẩn trích dẫn [source|chunk_id].
""".strip()

    answer = ask_gemini(genai, GEMINI_MODEL_ANSWER, sys_prompt, user_prompt, json_mode=False)

    _LAST["answer"] = (_LAST.get("answer", "") + "\n" + answer).strip()

    if CONTINUE_RETRIEVE:
        new_trace: List[Dict[str, Any]] = []
        for d, score in ranked:
            m = d.metadata or {}
            new_trace.append({
                "source": m.get("source", "?"),
                "chunk_id": m.get("chunk_id", -1),
                "score": float(score) if score is not None else None,
                "text": d.page_content,
            })
        _LAST["trace"] = new_trace

    return answer, _LAST["trace"]

def judge_last() -> dict:
    if not ENABLE_JUDGE:
        return {"overall": None, "notes": "Judge disabled"}
    return _judge(_LAST.get("question", ""), _LAST.get("answer", ""), _LAST.get("trace", []), GEMINI_MODEL_JUDGE)
