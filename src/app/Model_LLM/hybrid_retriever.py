import os, json, re, unicodedata
from typing import List, Dict, Tuple
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers.ensemble import EnsembleRetriever

# ==== Tham số hybrid / rerank (bạn có thể chỉnh) ====
TOP_K = 22              # k cuối cùng dùng làm context
K_SEM = 20              # k semantic (FAISS) trước khi hợp nhất
K_LEX = 20              # k lexical (BM25) trước khi hợp nhất
MMR_FETCH_K = 80        # số lượng fetch để MMR đa dạng
MMR_LAMBDA = 0.45        # 0.35–0.5, thấp = đa dạng hơn

USE_RERANK = True
RERANK_CANDIDATES = 80
RERANK_TOP_K = TOP_K
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-12-v2"

# ==== Chuẩn hoá chữ cho BM25 & Query ====
# CASE_NORM: 'lower' (mặc định) hoặc 'upper'
CASE_NORM = os.environ.get("CASE_NORM", "lower").strip().lower()
if CASE_NORM not in ("lower", "upper"):
    CASE_NORM = "lower"

def _normalize_case(s: str) -> str:
    """Chuẩn hoá theo CASE_NORM + NFKC + gọn khoảng trắng."""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower() if CASE_NORM == "lower" else s.upper()

def normalize_query(q: str) -> str:
    """Hàm export để nơi gọi dùng trước khi search."""
    return _normalize_case(q or "")

# Vị trí data .txt (fallback nếu chưa có corpus.jsonl)
DATA_DIR = os.environ.get("DATA_DIR", "./src/app/Data/Data_All")
# Nơi lưu index FAISS đang dùng
FAISS_DIR = os.environ.get("FAISS_DIR", "./src/app/vectorstore/FAISS_Vector_All")
# Nơi lưu corpus JSONL để lần sau không phải load TXT lại
CORPUS_PATH = os.path.join(FAISS_DIR, "corpus.jsonl")

# ==== Clean text gọn ====
def _clean_text(s: str) -> str:
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def _split_text(text: str, chunk_size=1200, overlap=300) -> List[str]:
    # Split thô theo đoạn xuống dòng trước để giảm vỡ ý
    parts = []
    paragraphs = re.split(r"\n{2,}", text)
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # cắt sliding window
        start = 0
        while start < len(p):
            end = min(len(p), start + chunk_size)
            parts.append(p[start:end])
            if end == len(p): break
            start = max(end - overlap, 0)
    return parts

def _load_txt_folder(folder: str) -> Dict[str, str]:
    data = {}
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return data
    for fn in os.listdir(folder):
        if fn.lower().endswith(".txt"):
            with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                data[fn] = f.read()
    return data

def _save_corpus_jsonl(docs: List[Document]):
    os.makedirs(os.path.dirname(CORPUS_PATH), exist_ok=True)
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        for d in docs:
            # Lưu text KHÔNG prefix 'passage: ' để BM25 match keyword tốt hơn
            text = d.page_content
            if text.lower().startswith("passage: "):
                text = text[len("passage: "):]
            rec = {"text": text, "metadata": d.metadata}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def _load_corpus_jsonl() -> List[Document]:
    """
    Chỉ nạp nếu corpus đã được build với norm_case khớp CASE_NORM hiện tại.
    Nếu thiếu cờ hoặc không khớp → trả [] để buộc rebuild.
    """
    if not os.path.isfile(CORPUS_PATH):
        return []
    docs = []
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            meta = rec.get("metadata", {})
            # Kiểm tra cờ norm_case
            if meta.get("norm_case") != CASE_NORM:
                return []  # Force rebuild với chuẩn mới
            docs.append(Document(page_content=rec["text"], metadata=meta))
    return docs

def prepare_bm25_docs() -> List[Document]:
    """
    1) Thử nạp corpus.jsonl sẵn có (nếu norm_case khớp).
    2) Nếu chưa có/không khớp: đọc ./src/Data/*.txt, chuẩn hoá CASE_NORM,
       split chunk và lưu corpus.jsonl cho lần sau.
    """
    docs = _load_corpus_jsonl()
    if docs:
        return docs

    raw = _load_txt_folder(DATA_DIR)
    out_docs: List[Document] = []
    chunk_id = 0
    for fname, text in raw.items():
        t = _clean_text(text)
        if not t:
            continue
        t_norm = _normalize_case(t)  # <<< ép lowercase/uppercase đồng bộ cho BM25
        for piece in _split_text(t_norm, chunk_size=1200, overlap=300):
            out_docs.append(Document(
                page_content=piece,
                metadata={"source": fname, "page": -1, "chunk_id": chunk_id, "norm_case": CASE_NORM}
            ))
            chunk_id += 1

    if out_docs:
        _save_corpus_jsonl(out_docs)
    return out_docs

def build_hybrid_retriever(vs) -> EnsembleRetriever:
    """
    vs: VectorStore FAISS (đã load sẵn)
    Trả về EnsembleRetriever (BM25 + Semantic with MMR)
    """
    # semantic retriever (FAISS) + MMR
    sem = vs.as_retriever(
        search_type="mmr",
        search_kwargs={"k": K_SEM, "fetch_k": MMR_FETCH_K, "lambda_mult": MMR_LAMBDA}
    )

    # lexical retriever (BM25)
    bm25_docs = prepare_bm25_docs()
    bm25 = BM25Retriever.from_documents(bm25_docs)
    bm25.k = K_LEX

    # Hợp nhất (BM25 0.35, Semantic 0.65)
    ens = EnsembleRetriever(retrievers=[bm25, sem], weights=[0.35, 0.65])
    return ens

def rerank(query: str, docs: List[Document], top_k: int = RERANK_TOP_K) -> List[Tuple[Document, float]]:
    if not USE_RERANK or not docs:
        return [(d, None) for d in docs[:top_k]]
    from sentence_transformers import CrossEncoder
    ce = CrossEncoder(RERANK_MODEL)  # cache tại process
    pairs = [(query, d.page_content) for d in docs[:RERANK_CANDIDATES]]
    scores = ce.predict(pairs, convert_to_numpy=True).tolist()
    ranked = sorted(zip(docs[:RERANK_CANDIDATES], scores), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]
