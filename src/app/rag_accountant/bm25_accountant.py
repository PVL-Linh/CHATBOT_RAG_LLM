import os, json, re
from typing import List, Optional
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from app.config.paths import DATA_DIR_ACCOUNTANT, FAISS_DIR_ACCOUNTANT
from app.config.config_accountant import USE_BM25_ACCOUNTANT, CASE_NORM_ACCOUNTANT

_CORPUS_PATH = os.path.join(FAISS_DIR_ACCOUNTANT, "corpus.jsonl")
_FORCE_REBUILD = os.environ.get("FORCE_REBUILD_CORPUS_ACCOUNTANT","0").lower() not in ("0","false")

def _normalize_case(s: str, CASE=CASE_NORM_ACCOUNTANT) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s.lower() if CASE=="lower" else s.upper()

def _split(text: str, chunk_size=1200, overlap=300):
    text = re.sub(r"\s+\n", "\n", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    parts, i = [], 0
    while i < len(text):
        j = min(len(text), i + chunk_size)
        parts.append(text[i:j])
        if j == len(text): break
        i = max(0, j - overlap)
    return parts

def _scan_txt(folder: str):
    out = {}
    for root, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".txt"):
                full = os.path.join(root, fn)
                try:
                    out[os.path.relpath(full, folder)] = open(full, "r", encoding="utf-8", errors="ignore").read()
                except Exception:
                    pass
    return out

def _load_corpus_jsonl() -> List[Document]: 
    print(f"[DBG] Đọc corpus từ {_CORPUS_PATH}")
    if not os.path.isfile(_CORPUS_PATH): return []
    docs = []
    with open(_CORPUS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            meta = rec.get("metadata", {})
            if meta.get("norm_case") != CASE_NORM_ACCOUNTANT:
                return []
            docs.append(Document(page_content=rec["text"], metadata=meta))
    return docs

def _save_corpus_jsonl(docs: List[Document]):
    os.makedirs(os.path.dirname(_CORPUS_PATH), exist_ok=True)
    with open(_CORPUS_PATH, "w", encoding="utf-8") as f:
        for d in docs:
            text = d.page_content
            if text.lower().startswith("passage: "):
                text = text[len("passage: "):]
            f.write(json.dumps({"text": text, "metadata": d.metadata}, ensure_ascii=False) + "\n")

def _need_rebuild() -> bool:
    if _FORCE_REBUILD: return True
    if not os.path.isfile(_CORPUS_PATH): return True
    try:
        corpus_mtime = os.path.getmtime(_CORPUS_PATH)
        for root, _, files in os.walk(DATA_DIR_ACCOUNTANT):
            for fn in files:
                if fn.lower().endswith(".txt"):
                    if os.path.getmtime(os.path.join(root, fn)) > corpus_mtime:
                        return True
    except Exception:
        return True
    return False

_bm25_docs_cache: List[Document] = []
_bm25_retriever = None

def prepare_bm25_docs() -> List[Document]:
    global _bm25_docs_cache
    if _bm25_docs_cache:
        return _bm25_docs_cache

    if not _need_rebuild():
        docs = _load_corpus_jsonl()
        if docs:
            print(f"[DBG] Nạp corpus.jsonl ({len(docs)} chunks) từ {_CORPUS_PATH}")
            _bm25_docs_cache = docs
            return docs

    raw = _scan_txt(DATA_DIR_ACCOUNTANT)
    docs, cid = [], 0
    for fname, text in raw.items():
        t = _normalize_case(text)
        for piece in _split(t, 1200, 300):
            docs.append(Document(page_content=piece, metadata={"source": fname, "chunk_id": cid, "norm_case": CASE_NORM_ACCOUNTANT}))
            cid += 1
    if docs:
        _save_corpus_jsonl(docs)
        print(f"[DBG] Build corpus.jsonl mới: {len(docs)} chunks → {_CORPUS_PATH}")
    else:
        print(f"[WARN] DATA_DIR_HR rỗng: {DATA_DIR_ACCOUNTANT} — BM25 sẽ bị tắt.")
    _bm25_docs_cache = docs
    return docs

def get_bm25():
    global _bm25_retriever
    if not USE_BM25_ACCOUNTANT:
        return None
    if _bm25_retriever is not None:
        return _bm25_retriever
    docs = prepare_bm25_docs()
    if not docs:
        return None
    try:
        bm25 = BM25Retriever.from_documents(docs)
        bm25.k = 50
        _bm25_retriever = bm25
        return bm25
    except Exception as e:
        print(f"[WARN] BM25 init lỗi: {e}")
        return None
