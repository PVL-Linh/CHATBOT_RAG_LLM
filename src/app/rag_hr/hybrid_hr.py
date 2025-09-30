import time, re
from typing import List
from langchain_core.documents import Document
from .faiss_store_hr import load_vectorstore
from .bm25_hr import get_bm25
from .config_hr import (DEBUG_QE_HR, K_SEM_HR, K_LEX_HR, RAG_TOPK_HR as TOP_K_HR, MMR_FETCH_K_HR, MMR_LAMBDA_HR, 
                        W_SEM_HR, W_LEX_HR, USE_BM25_HR, FAST_MODE_HR, CASE_NORM_HR, FAISS_DIR_HR)


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip().lower()
    return s

def _wrrf_merge(list_a: List[Document], list_b: List[Document], w_a: float, w_b: float, c: int = 60) -> List[Document]:
    def key(d: Document):
        m = d.metadata or {}
        return (m.get("source"), m.get("chunk_id"))
    scores, keep = {}, {}
    for rank, d in enumerate(list_a):
        k = key(d); scores[k] = scores.get(k, 0.0) + w_a / (rank + c); keep[k] = d
    for rank, d in enumerate(list_b):
        k = key(d); scores[k] = scores.get(k, 0.0) + w_b / (rank + c); keep[k] = d
    order = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [keep[k] for k in order]

def build_lex_query(question: str, aliases=None, phrases=None) -> dict:
    """Hợp nhất canonical + aliases + phrases thành cụm lexicographic cho BM25."""
    q = _norm(question)
    parts = [q] if q else []
    # alias để trong "..."
    for a in (aliases or []):
        a = _norm(a)
        if a and a not in parts:
            parts.append(f"\"{a}\"")
    # phrases tăng trọng số lặp nhiều lần
    if phrases:
        for p in phrases:
            p = _norm(p)
            if p and f"\"{p}\"" not in parts:
                parts.append(f"\"{p}\"")
    lex_q = " ".join(parts).strip()
    if DEBUG_QE_HR:
        print(f"[LEX_QUERY] {lex_q}")
    return {"lex_query": lex_q, "canonical": q}

def hybrid_retrieve(vs, question: str, lex_query: str = None,
                    k_sem: int = K_SEM_HR, k_lex: int = K_LEX_HR, top_k: int = TOP_K_HR) -> List[Document]:
    q_sem = f"query: {_norm(question)}"
    t0 = time.time()
    sem_docs = vs.max_marginal_relevance_search(q_sem, k=k_sem, fetch_k=MMR_FETCH_K_HR, lambda_mult=MMR_LAMBDA_HR)
    t1 = time.time()

    if FAST_MODE_HR:
        return sem_docs[:top_k]

    lex_docs: List[Document] = []
    bm25 = get_bm25()
    if bm25 and lex_query:
        try:
            try:
                lex_docs = bm25.invoke(_norm(lex_query))  # LC >= 0.1.46
            except Exception:
                lex_docs = bm25.get_relevant_documents(_norm(lex_query))
        except Exception as e:
            print(f"[WARN] BM25 query lỗi: {e}")
    t2 = time.time()

    merged = sem_docs if not lex_docs else _wrrf_merge(sem_docs, lex_docs, w_a=W_SEM_HR, w_b=W_LEX_HR, c=60)
    t3 = time.time()
    # Debug peek
    if DEBUG_QE_HR:
        def _peek(docs, tag):
            tops = " | ".join(f"{(d.metadata or {}).get('source','?')}#{(d.metadata or {}).get('chunk_id',-1)}" for d in docs[:5])
            print(f"[{tag}] {tops}")
        _peek(sem_docs, "SEM")
        _peek(lex_docs, "LEX")
        _peek(merged,   "MRG")

    return merged[:max(top_k, min(k_sem, k_lex))]

def load_vs():
    return load_vectorstore()
