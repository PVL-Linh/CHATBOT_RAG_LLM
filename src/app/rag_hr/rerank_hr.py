# -*- coding: utf-8 -*-
from typing import List, Tuple
from langchain_core.documents import Document
from .config_hr import USE_RERANK_HR, RERANK_MODEL_HR, RERANK_CANDIDATES_HR, RERANK_TOP_K_HR, METRICS_HR

_ce_model = None

def rerank(question: str, docs: List[Document], top_k: int = RERANK_TOP_K_HR) -> List[Tuple[Document, float]]:
    if not USE_RERANK_HR or not docs:
        return [(d, None) for d in docs[:top_k]]
    try:
        from sentence_transformers import CrossEncoder
    except Exception as e:
        print(f"[WARN] sentence-transformers chưa sẵn: {e}")
        return [(d, None) for d in docs[:top_k]]

    global _ce_model
    if _ce_model is None:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        try:
            _ce_model = CrossEncoder(RERANK_MODEL_HR, device=device)
            if METRICS_HR:
                print(f"[DBG] Load CrossEncoder '{RERANK_MODEL_HR}' on {device}")
        except Exception as e:
            print(f"[WARN] Không khởi tạo CrossEncoder: {e}")
            return [(d, None) for d in docs[:top_k]]

    pairs = [(question, d.page_content) for d in docs[:RERANK_CANDIDATES_HR]]
    try:
        scores = _ce_model.predict(pairs)
        scores = scores.tolist() if hasattr(scores, "tolist") else list(scores)
    except Exception as e:
        print(f"[WARN] CrossEncoder.predict lỗi: {e}")
        return [(d, None) for d in docs[:top_k]]

    ranked = sorted(list(zip(docs[:RERANK_CANDIDATES_HR], scores)), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]
