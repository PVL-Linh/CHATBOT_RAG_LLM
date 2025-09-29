import os
import json
from typing import List, Optional
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from .config_hr import DATA_DIR_HR, CASE_NORM, CORPUS_PATH
from .utils_hr import clean_text, split_text, normalize_case

_bm25_docs_cache: List[Document] = []
_bm25_retriever_cache: Optional[BM25Retriever] = None

def _save_corpus_jsonl(docs: List[Document]):
    os.makedirs(os.path.dirname(CORPUS_PATH), exist_ok=True)
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        for d in docs:
            text = d.page_content
            if text.lower().startswith("passage: "):
                text = text[len("passage: ") :]
            rec = {"text": text, "metadata": d.metadata}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def _load_corpus_jsonl() -> List[Document]:
    if not os.path.isfile(CORPUS_PATH):
        return []
    docs = []
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            meta = rec.get("metadata", {})
            if meta.get("norm_case") != CASE_NORM:
                return []
            docs.append(Document(page_content=rec["text"], metadata=meta))
    return docs

def _load_txt_folder(folder: str) -> dict:
    data = {}
    if not os.path.isdir(folder):
        print(f"[WARN] DATA_DIR không tồn tại: {folder}")
        return data
    count = 0
    for root, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".txt"):
                full = os.path.join(root, fn)
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        data[os.path.relpath(full, folder)] = f.read()
                        count += 1
                except Exception as e:
                    print(f"[WARN] Không đọc được: {full} ({e})")
    print(f"[DBG] Quét TXT: folder={folder} | files={count}")
    return data

def prepare_bm25_docs() -> List[Document]:
    global _bm25_docs_cache
    if _bm25_docs_cache:
        return _bm25_docs_cache

    docs = _load_corpus_jsonl()
    if docs:
        print(f"[DBG] Nạp corpus.jsonl ({len(docs)} chunks) từ {CORPUS_PATH}")
        _bm25_docs_cache = docs
        return docs

    raw = _load_txt_folder(DATA_DIR_HR)
    out_docs: List[Document] = []
    chunk_id = 0
    for fname, text in raw.items():
        t = clean_text(text)
        if not t:
            continue
        t_norm = normalize_case(t, CASE_NORM)
        for piece in split_text(t_norm, chunk_size=1200, overlap=300):
            out_docs.append(
                Document(
                    page_content=piece,
                    metadata={"source": fname, "page": -1, "chunk_id": chunk_id, "norm_case": CASE_NORM},
                )
            )
            chunk_id += 1

    if out_docs:
        _save_corpus_jsonl(out_docs)
        print(f"[DBG] Build corpus.jsonl mới: chunks={len(out_docs)} → {CORPUS_PATH}")
    else:
        print(f"[WARN] DATA_DIR rỗng: {DATA_DIR_HR} — BM25 sẽ bị tắt (fallback semantic-only).")

    _bm25_docs_cache = out_docs
    return out_docs

def get_bm25_retriever(k_lex: int) -> Optional[BM25Retriever]:
    global _bm25_retriever_cache
    if _bm25_retriever_cache is not None:
        return _bm25_retriever_cache
    bm25_docs = prepare_bm25_docs()
    if not bm25_docs:
        return None
    try:
        bm25 = BM25Retriever.from_documents(bm25_docs)
        bm25.k = k_lex
        _bm25_retriever_cache = bm25
        return bm25
    except Exception as e:
        print(f"[WARN] BM25Retriever lỗi: {e} → tắt BM25.")
        _bm25_retriever_cache = None
        return None
