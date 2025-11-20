import os, json, re, unicodedata
from typing import List, Dict, Tuple
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers.ensemble import EnsembleRetriever
from sentence_transformers import SentenceTransformer
from app.config.paths import DATA_DIR, FAISS_ALL_DIR
from app.config.settings import hybrid_retriever as chatall
from sentence_transformers import CrossEncoder

CHUNKS = 1000
OVERLAP = 250
# ==== Tham số hybrid / rerank (bạn có thể chỉnh) ====
TOP_K = chatall.TOP_K              # k cuối cùng dùng làm context
K_SEM = chatall.K_SEM              # k semantic (FAISS) trước khi hợp nhất
K_LEX = chatall.K_LEX              # k lexical (BM25) trước khi hợp nhất
MMR_FETCH_K = chatall.MMR_FETCH_K        # số lượng fetch để MMR đa dạng
MMR_LAMBDA = chatall.MMR_LAMBDA        # 0.35–0.5, thấp = đa dạng hơn

USE_RERANK = chatall.USE_RERANK
RERANK_CANDIDATES = chatall.RERANK_CANDIDATES
RERANK_TOP_K = chatall.RERANK_TOP_K
RERANK_MODEL = chatall.RERANK_MODEL

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

# Nơi lưu corpus JSONL để lần sau không phải load TXT lại
CORPUS_PATH = os.path.join(FAISS_ALL_DIR, "corpus.jsonl")

# ==== Clean text gọn ====
def _clean_text(s: str) -> str:
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def _split_text(text: str, chunk_size: int = CHUNKS, overlap: int = OVERLAP):
    """
    Chunk theo câu, nhưng giới hạn chunk_size (ký tự)
    và giữ overlap (ký tự) giữa các chunk, giống semantics chunk_overlap.
    """
    if not text or not text.strip():
        return []

    # Tách câu, có thể chỉnh regex nếu cần
    sentences = re.split(r'(?<=[.!?。！？])\s+', text)
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0  # tổng số ký tự trong current

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        sent_len = len(sent)

        # Nếu thêm câu này vào vượt quá chunk_size -> chốt chunk hiện tại
        # (current không rỗng thì mới chốt, để tránh chunk rỗng)
        if current and current_len + 1 + sent_len > chunk_size:
            # Đẩy chunk hiện tại
            chunks.append(" ".join(current))

            # Tính overlap theo ký tự
            if overlap > 0 and current:
                kept: List[str] = []
                total = 0
                # đi từ cuối về đầu, giữ lại đến khi đủ overlap ký tự
                for s in reversed(current):
                    if total >= overlap and kept:
                        break
                    kept.append(s)
                    total += len(s)
                current = list(reversed(kept))
                current_len = sum(len(s) for s in current)
            else:
                current = []
                current_len = 0

        # Thêm câu hiện tại vào chunk
        if current:
            # +1 cho khoảng trắng khi join
            current_len += 1 + sent_len
        else:
            current_len = sent_len
        current.append(sent)

    # Đẩy phần còn lại
    if current:
        chunks.append(" ".join(current))

    return chunks



def _load_txt_folder(folder: str) -> Dict[str, str]:
    data = {}
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return data

    # for root, _, files in os.walk(folder):
    #     for fn in files:
    #         if fn.lower().endswith(".txt"):
    #             file_path = os.path.join(root, fn)
    #             rel_path = os.path.relpath(file_path, folder)
    #             with open(file_path, "r", encoding="utf-8") as f:
    #                 data[rel_path] = f.read()
    for root, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".txt"):
                file_path = os.path.join(root, fn)
                rel_path = os.path.relpath(file_path, folder)
                with open(file_path, "r", encoding="utf-8") as f:
                    data[rel_path] = f.read(1024*1024*10)
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
    if not os.path.isfile(CORPUS_PATH):
        return []
    docs: List[Document] = []
    try:
        with open(CORPUS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    # Nếu có line hỏng -> bỏ cả corpus, rebuild lại
                    return []
                meta = rec.get("metadata", {})
                if meta.get("norm_case") != CASE_NORM:
                    return []
                docs.append(Document(page_content=rec["text"], metadata=meta))
    except Exception as e:
        print(f"[WARN] Failed to load corpus.jsonl: {e} -> rebuild")
        return []
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
        for piece in _split_text(t_norm, chunk_size=CHUNKS, overlap=OVERLAP):
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

    weights_str = os.environ.get("ENSEMBLE_WEIGHTS", "[0.35, 0.65]")
    try:
        weights = json.loads(weights_str)
        if len(weights) != 2 or sum(weights) != 1.0:
            raise ValueError("Invalid weights")
    except Exception:  
        # Hợp nhất (BM25 0.35, Semantic 0.65)
        weights = [0.35, 0.65]
    ens = EnsembleRetriever(retrievers=[bm25, sem], weights=weights)
    return ens

# Trong rerank (hybrid_retriever.py)
def rerank(query: str, docs: List[Document], top_k: int = RERANK_TOP_K) -> List[Tuple[Document, float]]:
    if not USE_RERANK or not docs:
        return [(d, None) for d in docs[:top_k]]
    from sentence_transformers import CrossEncoder
    try:
        ce = CrossEncoder(RERANK_MODEL)  # Di chuyển vào đây
        pairs = [(query, d.page_content) for d in docs[:RERANK_CANDIDATES]]
        scores = ce.predict(pairs, convert_to_numpy=True).tolist()
        ranked = sorted(zip(docs[:RERANK_CANDIDATES], scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
    except Exception as e:
        print(f"[ERROR] Rerank failed: {e} - Fallback to no rerank")
        return [(d, None) for d in docs[:top_k]]