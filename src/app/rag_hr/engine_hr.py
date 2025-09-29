import re
import time
from typing import Tuple, List, Dict, Any
from langchain_core.documents import Document

from .config_hr import (
    TOP_K, K_SEM, K_LEX, MAX_CHARS_CTX, ENABLE_JUDGE,
    GEMINI_MODEL_ANSWER, GEMINI_MODEL_JUDGE, METRICS,
    CONTINUE_RETRIEVE, W_SEM, W_LEX, PHRASE_BOOST_TIMES, DEBUG_QE, MMR_FETCH_K, MMR_LAMBDA
)
from .faiss_store_hr import load_faiss_vs
from .hybrid_hr import hybrid_retrieve
from .rerank_hr import rerank
from .context_hr import build_context
from .gemini_client_hr import init_gemini, ask_gemini
from .prompts_hr import get_system_prompt
from .utils_hr import clip
from .prf import prf_expand_from_semantic
from .query_rewrite_llm import llm_expand_query
from .postprocess import strip_citations

_LAST: Dict[str, Any] = {"question": "", "answer": "", "trace": [], "lex_query": ""}

def _dedup_quoted_phrases(s: str) -> str:
    phrases = [m.strip() for m in re.findall(r'"([^"]+)"', s)]
    seen = set(); uniq = []
    for p in phrases:
        if p and p not in seen:
            seen.add(p); uniq.append(f'"{p}"')
    base = re.sub(r'"[^"]+"', ' ', s)
    base = re.sub(r'\s+', ' ', base).strip()
    out = (base + ' ' + ' '.join(uniq)).strip()
    return re.sub(r'\s+', ' ', out)

def build_lex_query(question: str, vs=None) -> Dict[str, str]:
    # 1) LLM rewrite
    qexp_llm = llm_expand_query(question)
    lex_q = qexp_llm["lex_query"]
    canonical = qexp_llm["canonical"]

    # 2) PRF
    if vs is None:
        vs = load_faiss_vs()
    q_sem = f"query: {question}"
    sem_docs_small = vs.max_marginal_relevance_search(q_sem, k=6, fetch_k=MMR_FETCH_K, lambda_mult=MMR_LAMBDA)
    prf_phrases = prf_expand_from_semantic(sem_docs_small)
    if prf_phrases:
        boosted = []
        for p in prf_phrases:
            boosted.extend([f"\"{p}\""] * max(1, PHRASE_BOOST_TIMES))
        lex_q = " ".join([lex_q] + boosted)

    lex_q = _dedup_quoted_phrases(lex_q)
    if DEBUG_QE:
        print(f"[LEX_QUERY] {lex_q}")
    return {"lex_query": lex_q, "canonical": canonical}

def answer_with_rag(question: str) -> Tuple[str, List[Dict[str, Any]]]:
    vs = load_faiss_vs()

    # 0) lex_query
    qexp = build_lex_query(question, vs=vs)
    lex_q = qexp["lex_query"]

    # 1) Retrieve
    t0 = time.time()
    docs = hybrid_retrieve(
        vs, question, k_sem=K_SEM, k_lex=K_LEX, top_k=TOP_K,
        lex_query=lex_q, w_sem=W_SEM, w_lex=W_LEX
    )
    t1 = time.time()

    # 2) Rerank
    ranked = rerank(question, docs, top_k=TOP_K)
    t2 = time.time()

    # 3) Context + trace
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

    # 4) LLM trả lời
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
    answer_raw = ask_gemini(genai, GEMINI_MODEL_ANSWER, sys_prompt, user_prompt, json_mode=False)
    t5 = time.time()

    answer = strip_citations(answer_raw)  # ← loại thẻ citation ở đầu ra

    if METRICS:
        print(
            "[METRIC] t_retrieve={:.3f}s | t_rerank={:.3f}s | t_build={:.3f}s | t_llm={:.3f}s | t_total={:.3f}s".format(
                (t1 - t0), (t2 - t1), (t3 - t2), (t5 - t4), (t5 - t0)
            )
        )

    _LAST.update({"question": question, "answer": answer, "trace": trace, "lex_query": lex_q})
    return answer, trace

def continue_with_last(followup_text: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    if not _LAST.get("trace"):
        raise RuntimeError("Không có ngữ cảnh trước để 'viết tiếp'. Hãy hỏi một câu trước.")

    vs = load_faiss_vs()

    if CONTINUE_RETRIEVE:
        combined_q = f"{_LAST.get('question','')} {followup_text}".strip()
        docs = hybrid_retrieve(vs, combined_q, k_sem=K_SEM, k_lex=K_LEX, top_k=TOP_K,
                               lex_query=build_lex_query(combined_q, vs=vs)["lex_query"],
                               w_sem=W_SEM, w_lex=W_LEX)
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

    answer_raw = ask_gemini(genai, GEMINI_MODEL_ANSWER, sys_prompt, user_prompt, json_mode=False)
    answer = strip_citations(answer_raw)
    _LAST["answer"] = (_LAST.get("answer", "") + "\n" + answer).strip()
    return answer, _LAST["trace"]

def get_last_debug() -> Dict[str, Any]:
    return {"lex_query": _LAST.get("lex_query"), "question": _LAST.get("question")}
