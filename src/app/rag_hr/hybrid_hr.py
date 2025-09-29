import time
from typing import List, Tuple, Dict, Any as _Any
from langchain_core.documents import Document

from .config_hr import K_SEM, K_LEX, TOP_K, MMR_FETCH_K, MMR_LAMBDA, FAST_MODE, USE_BM25, METRICS
from .bm25_hr import get_bm25_retriever
from .utils_hr import normalize_case
from .config_hr import CASE_NORM

def _wrrf_merge(list_a: List[Document], list_b: List[Document], w_a: float, w_b: float, c: int = 60) -> List[Document]:
    def _key(d: Document) -> Tuple[_Any, _Any, _Any]:
        m = d.metadata or {}
        return (m.get("source"), m.get("chunk_id"), (d.page_content or "")[:40])

    scores: Dict[Tuple[_Any, _Any, _Any], float] = {}
    order: Dict[Tuple[_Any, _Any, _Any], Document] = {}

    for rank, d in enumerate(list_a):
        k = _key(d)
        scores[k] = scores.get(k, 0.0) + (0.0 if w_a == 0 else w_a) / (rank + c)
        order[k] = d
    for rank, d in enumerate(list_b):
        k = _key(d)
        scores[k] = scores.get(k, 0.0) + (0.0 if w_b == 0 else w_b) / (rank + c)
        order[k] = d

    merged = sorted(order.keys(), key=lambda k: scores[k], reverse=True)
    return [order[k] for k in merged]

def hybrid_retrieve(vs, question: str, k_sem: int = K_SEM, k_lex: int = K_LEX, top_k: int = TOP_K) -> List[Document]:
    t0 = time.time()
    q_norm = normalize_case(question, CASE_NORM)
    q_sem = f"query: {q_norm.strip()}"

    # FAISS: dùng MMR để đa dạng
    sem_docs = vs.max_marginal_relevance_search(q_sem, k=k_sem, fetch_k=MMR_FETCH_K, lambda_mult=MMR_LAMBDA)
    t1 = time.time()

    # FAST_MODE: bỏ BM25 để tối ưu tốc độ
    if FAST_MODE or not USE_BM25:
        if METRICS:
            print(f"[DBG] FAST_MODE={FAST_MODE} → FAISS(MMR) sem={len(sem_docs)} | {t1-t0:.3f}s")
        return sem_docs[:top_k]

    # BM25
    lex_docs: List[Document] = []
    bm25 = get_bm25_retriever(k_lex)
    if bm25 is not None:
        try:
            lex_docs = bm25.get_relevant_documents(q_norm)
        except Exception as e:
            print(f"[WARN] BM25.get_relevant_documents lỗi: {e} → fallback semantic-only.")
            lex_docs = []
    t2 = time.time()

    merged = sem_docs if not lex_docs else _wrrf_merge(sem_docs, lex_docs, w_a=0.65, w_b=0.35, c=60)
    t3 = time.time()

    if METRICS:
        print(f"[DBG] sem={len(sem_docs)} ({t1-t0:.3f}s) | bm25={len(lex_docs)} ({t2-t1:.3f}s) | merge=({t3-t2:.3f}s)")
    return merged[:max(top_k, min(k_sem, k_lex))]
