import time
from typing import List, Tuple, Optional
from langchain_core.documents import Document
from .config_hr import USE_RERANK, RERANK_CANDIDATES, RERANK_TOP_K, RERANK_MODEL, METRICS
from .utils_hr import select_device

_ce_model_cache = None

def rerank(question: str, docs: List[Document], top_k: Optional[int] = None) -> List[Tuple[Document, Optional[float]]]:
    if top_k is None:
        top_k = RERANK_TOP_K
    if not USE_RERANK or not docs:
        return [(d, None) for d in docs[:top_k]]
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except Exception as e:
        print(f"[WARN] Không thể nạp sentence-transformers ({e}). Bỏ qua rerank.")
        return [(d, None) for d in docs[:top_k]]

    global _ce_model_cache
    if _ce_model_cache is None:
        device = select_device()
        try:
            _ce_model_cache = CrossEncoder(RERANK_MODEL, device=device)
            if METRICS:
                print(f"[DBG] Load CrossEncoder '{RERANK_MODEL}' on {device}")
        except Exception as e:
            print(f"[WARN] Không thể khởi tạo CrossEncoder '{RERANK_MODEL}': {e}. Bỏ qua rerank.")
            return [(d, None) for d in docs[:top_k]]

    pairs = [(question, d.page_content) for d in docs[:RERANK_CANDIDATES]]
    t0 = time.time()
    try:
        scores = _ce_model_cache.predict(pairs)
        scores = scores.tolist() if hasattr(scores, "tolist") else list(scores)
    except Exception as e:
        print(f"[WARN] CrossEncoder.predict lỗi: {e}. Bỏ qua rerank.")
        return [(d, None) for d in docs[:top_k]]
    t1 = time.time()

    ranked = sorted(list(zip(docs[:RERANK_CANDIDATES], scores)), key=lambda x: x[1], reverse=True)
    if METRICS:
        print(f"[DBG] rerank {len(pairs)} pairs → {top_k} kept ({t1-t0:.3f}s)")
    return ranked[:top_k]
