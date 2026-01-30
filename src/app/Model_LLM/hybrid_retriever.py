# import threading
# import os, json, re, unicodedata
# from typing import List, Dict, Tuple
# from langchain_core.documents import Document
# from langchain_community.retrievers import BM25Retriever
# from langchain.retrievers.ensemble import EnsembleRetriever
# # from sentence_transformers import SentenceTransformer
# import torch
# from app.config.paths import DATA_DIR, FAISS_ALL_DIR
# from app.config.settings import hybrid_retriever as chatall
# from sentence_transformers import CrossEncoder

# CHUNKS = 800
# OVERLAP = 250
# # ==== Tham số hybrid / rerank (bạn có thể chỉnh) ====
# TOP_K = chatall.TOP_K             # k cuối cùng dùng làm context
# K_SEM = chatall.K_SEM              # k semantic (FAISS) trước khi hợp nhất
# K_LEX = chatall.K_LEX              # k lexical (BM25) trước khi hợp nhất
# MMR_FETCH_K = chatall.MMR_FETCH_K        # số lượng fetch để MMR đa dạng
# MMR_LAMBDA = chatall.MMR_LAMBDA        # 0.35–0.5, thấp = đa dạng hơn

# USE_RERANK = chatall.USE_RERANK
# RERANK_CANDIDATES = chatall.RERANK_CANDIDATES
# RERANK_TOP_K = chatall.RERANK_TOP_K
# RERANK_MODEL = chatall.RERANK_MODEL

# CASE_NORM = os.environ.get("CASE_NORM", "lower").strip().lower()
# if CASE_NORM not in ("lower", "upper"):
#     CASE_NORM = "lower"

# def _normalize_case(s: str) -> str:
#     """Chuẩn hoá theo CASE_NORM + NFKC + gọn khoảng trắng."""
#     s = unicodedata.normalize("NFKC", s or "")
#     s = re.sub(r"\s+", " ", s).strip()
#     return s.lower() if CASE_NORM == "lower" else s.upper()

# def normalize_query(q: str) -> str:
#     """Hàm export để nơi gọi dùng trước khi search."""
#     return _normalize_case(q or "")

# # Nơi lưu corpus JSONL để lần sau không phải load TXT lại
# CORPUS_PATH = os.path.join(FAISS_ALL_DIR, "corpus.jsonl")

# # ==== Clean text gọn ====
# def _clean_text(s: str) -> str:
#     s = re.sub(r"\s+\n", "\n", s)
#     s = re.sub(r"\n{3,}", "\n\n", s)
#     s = re.sub(r"[ \t]{2,}", " ", s)
#     return s.strip()

# def _split_text(text: str, chunk_size: int = CHUNKS, overlap: int = OVERLAP):
#     """
#     Chunk theo câu, nhưng giới hạn chunk_size (ký tự)
#     và giữ overlap (ký tự) giữa các chunk, giống semantics chunk_overlap.
#     """
#     if not text or not text.strip():
#         return []

#     # Tách câu, có thể chỉnh regex nếu cần
#     sentences = re.split(r'(?<=[.!?。！？])\s+', text)
#     chunks: List[str] = []
#     current: List[str] = []
#     current_len = 0  # tổng số ký tự trong current

#     for sent in sentences:
#         sent = sent.strip()
#         if not sent:
#             continue
#         sent_len = len(sent)
#         if current and current_len + 1 + sent_len > chunk_size:
#             chunks.append(" ".join(current))

#             if overlap > 0 and current:
#                 kept: List[str] = []
#                 total = 0
#                 for s in reversed(current):
#                     if total >= overlap and kept:
#                         break
#                     kept.append(s)
#                     total += len(s)
#                 current = list(reversed(kept))
#                 current_len = sum(len(s) for s in current)
#             else:
#                 current = []
#                 current_len = 0

#         if current:
#             current_len += 1 + sent_len
#         else:
#             current_len = sent_len
#         current.append(sent)
#     if current:
#         chunks.append(" ".join(current))

#     return chunks



# def _load_txt_folder(folder: str) -> Dict[str, str]:
#     data = {}
#     folder = os.path.abspath(folder)
#     if not os.path.isdir(folder):
#         return data

#     # for root, _, files in os.walk(folder):
#     #     for fn in files:
#     #         if fn.lower().endswith(".txt"):
#     #             file_path = os.path.join(root, fn)
#     #             rel_path = os.path.relpath(file_path, folder)
#     #             with open(file_path, "r", encoding="utf-8") as f:
#     #                 data[rel_path] = f.read()
#     for root, _, files in os.walk(folder):
#         for fn in files:
#             if fn.lower().endswith(".txt"):
#                 file_path = os.path.join(root, fn)
#                 rel_path = os.path.relpath(file_path, folder)
#                 with open(file_path, "r", encoding="utf-8") as f:
#                     data[rel_path] = f.read(1024*1024*10)
#     return data

# def _save_corpus_jsonl(docs: List[Document]):
#     os.makedirs(os.path.dirname(CORPUS_PATH), exist_ok=True)
#     with open(CORPUS_PATH, "w", encoding="utf-8") as f:
#         for d in docs:
#             text = d.page_content
#             if text.lower().startswith("passage: "):
#                 text = text[len("passage: "):]
#             rec = {"text": text, "metadata": d.metadata}
#             f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# def _load_corpus_jsonl() -> List[Document]:
#     if not os.path.isfile(CORPUS_PATH):
#         return []
#     docs: List[Document] = []
#     try:
#         with open(CORPUS_PATH, "r", encoding="utf-8") as f:
#             for line in f:
#                 line = line.strip()
#                 if not line:
#                     continue
#                 try:
#                     rec = json.loads(line)
#                 except json.JSONDecodeError:
#                     return []
#                 meta = rec.get("metadata", {})
#                 if meta.get("norm_case") != CASE_NORM:
#                     return []
#                 docs.append(Document(page_content=rec["text"], metadata=meta))
#     except Exception as e:
#         print(f"[WARN] Failed to load corpus.jsonl: {e} -> rebuild")
#         return []
#     return docs


# def prepare_bm25_docs() -> List[Document]:
#     """
#     1) Thử nạp corpus.jsonl sẵn có (nếu norm_case khớp).
#     2) Nếu chưa có/không khớp: đọc ./src/Data/*.txt, chuẩn hoá CASE_NORM,
#        split chunk và lưu corpus.jsonl cho lần sau.
#     """
#     docs = _load_corpus_jsonl()
#     if docs:
#         return docs

#     raw = _load_txt_folder(DATA_DIR)
#     out_docs: List[Document] = []
#     chunk_id = 0
#     for fname, text in raw.items():
#         t = _clean_text(text)
#         if not t:
#             continue
#         t_norm = _normalize_case(t)
#         for piece in _split_text(t_norm, chunk_size=CHUNKS, overlap=OVERLAP):
#             out_docs.append(Document(
#                 page_content=piece,
#                 metadata={"page": -1, "chunk_id": chunk_id, "norm_case": CASE_NORM}
#             ))
#             chunk_id += 1

#     if out_docs:
#         _save_corpus_jsonl(out_docs)
#     return out_docs

# def build_hybrid_retriever(vs) -> EnsembleRetriever:
#     """
#     vs: VectorStore FAISS (đã load sẵn)
#     Trả về EnsembleRetriever (BM25 + Semantic with MMR)
#     """
#     sem = vs.as_retriever(
#         search_type="mmr",
#         search_kwargs={"k": K_SEM, "fetch_k": MMR_FETCH_K, "lambda_mult": MMR_LAMBDA}
#     )

#     bm25_docs = prepare_bm25_docs()
#     bm25 = BM25Retriever.from_documents(bm25_docs)
#     bm25.k = K_LEX

#     weights_str = os.environ.get("ENSEMBLE_WEIGHTS", "[0.35, 0.65]")
#     try:
#         weights = json.loads(weights_str)
#         if len(weights) != 2 or sum(weights) != 1.0:
#             raise ValueError("Invalid weights")
#     except Exception:  
#         weights = [0.35, 0.65]
#     ens = EnsembleRetriever(retrievers=[bm25, sem], weights=weights)
#     return ens
# _reranker = None
# _reranker_lock = threading.Lock()

# def _get_reranker():
#     global _reranker
#     if _reranker is None:
#         with _reranker_lock:
#             if _reranker is None:
#                 device = "cuda" if torch.cuda.is_available() else "cpu"
#                 print(f"[Reranker] Loading {RERANK_MODEL} on {device}... (chỉ load 1 lần)")
#                 _reranker = CrossEncoder(
#                     RERANK_MODEL,
#                     device=device,
#                     max_length=512,
#                     activation_fn=torch.nn.Sigmoid()
#                 )
#     return _reranker

# def rerank(query: str, docs: List[Document], top_k: int = RERANK_TOP_K):
#     try:
#         top_k = int(top_k)
#     except (TypeError, ValueError):
#         try:
#             top_k = int(RERANK_TOP_K)
#         except Exception:
#             top_k = 14

#     if not USE_RERANK or not docs:
#         return [(d, None) for d in docs[:top_k]]

#     if len(docs) <= top_k:
#         return [(d, None) for d in docs[:top_k]]
    
#     try:
#         ce = _get_reranker()
#         pairs = [(query, d.page_content) for d in docs[:RERANK_CANDIDATES]]
#         scores = ce.predict(pairs, batch_size=64)
#         ranked = sorted(
#             zip(docs[:RERANK_CANDIDATES], scores),
#             key=lambda x: x[1],
#             reverse=True,
#         )
#         result = ranked[:top_k]
#         if torch.cuda.is_available():
#             torch.cuda.empty_cache()
#         return result
#     except Exception as e:
#         print(f"[Rerank lỗi] {e}")
#         return [(d, None) for d in docs[:top_k]]


# # # Trong rerank (hybrid_retriever.py)
# # def rerank(query: str, docs: List[Document], top_k: int = RERANK_TOP_K) -> List[Tuple[Document, float]]:
# #     if not USE_RERANK or not docs:
# #         return [(d, None) for d in docs[:top_k]]
# #     from sentence_transformers import CrossEncoder
# #     try:
# #         ce = CrossEncoder(RERANK_MODEL)  # Di chuyển vào đây
# #         pairs = [(query, d.page_content) for d in docs[:RERANK_CANDIDATES]]
# #         scores = ce.predict(pairs, convert_to_numpy=True).tolist()
# #         ranked = sorted(zip(docs[:RERANK_CANDIDATES], scores), key=lambda x: x[1], reverse=True)
# #         return ranked[:top_k]
# #     except Exception as e:
# #         print(f"[ERROR] Rerank failed: {e} - Fallback to no rerank")
# #         return [(d, None) for d in docs[:top_k]]

from __future__ import annotations

import os
import json
import re
import unicodedata
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers.ensemble import EnsembleRetriever
import torch
from sentence_transformers import CrossEncoder
from app.config.paths import DATA_DIR, FAISS_ALL_DIR
from app.config.settings import hybrid_retriever as chatall

# Tham số chung (giữ nguyên)
CHUNKS = 800
OVERLAP = 250

TOP_K = chatall.TOP_K             # k cuối cùng dùng làm context
K_SEM = chatall.K_SEM             # k semantic (FAISS) trước khi hợp nhất
K_LEX = chatall.K_LEX             # k lexical (BM25) trước khi hợp nhất
MMR_FETCH_K = chatall.MMR_FETCH_K # số lượng fetch để MMR đa dạng
MMR_LAMBDA = chatall.MMR_LAMBDA   # 0.35–0.5, thấp = đa dạng hơn

USE_RERANK = chatall.USE_RERANK
RERANK_CANDIDATES = chatall.RERANK_CANDIDATES
RERANK_TOP_K = chatall.RERANK_TOP_K
RERANK_MODEL = chatall.RERANK_MODEL

CASE_NORM = os.environ.get("CASE_NORM", "lower").strip().lower()
if CASE_NORM not in ("lower", "upper"):
    CASE_NORM = "lower"

# Nơi lưu corpus JSONL mặc định
DEFAULT_CORPUS_PATH = os.path.join(FAISS_ALL_DIR, "corpus.jsonl")
Path_corpus_path = Path(DEFAULT_CORPUS_PATH)

@dataclass
class HybridConfig:
    data_dir: str = str(DATA_DIR)
    corpus_path: str = DEFAULT_CORPUS_PATH

    chunk_size: int = CHUNKS
    overlap: int = OVERLAP

    top_k: int = TOP_K
    k_sem: int = K_SEM
    k_lex: int = K_LEX
    mmr_fetch_k: int = MMR_FETCH_K
    mmr_lambda: float = MMR_LAMBDA

    use_rerank: bool = USE_RERANK
    rerank_candidates: int = RERANK_CANDIDATES
    rerank_top_k: int = RERANK_TOP_K
    rerank_model: str = RERANK_MODEL

    case_norm: str = CASE_NORM
    ensemble_weights: Optional[List[float]] = None


class HybridRetrieverManager:
    """
    Quản lý:
    - Load TXT + chunk + cache corpus.jsonl
    - Xây BM25 + semantic + Ensemble retriever
    - Rerank bằng CrossEncoder
    """

    def __init__(self, cfg: Optional[HybridConfig] = None):
        self.cfg = cfg or HybridConfig()
        self._init_weights()
        self._reranker_lock = threading.Lock()
        self._reranker: Optional[CrossEncoder] = None

    # ---------- Weights ----------
    def _init_weights(self):
        if self.cfg.ensemble_weights is not None:
            return
        weights_str = os.environ.get("ENSEMBLE_WEIGHTS", "[0.35, 0.65]")
        try:
            w = json.loads(weights_str)
            if len(w) != 2 or abs(sum(w) - 1.0) > 1e-6:
                raise ValueError("Invalid weights")
        except Exception:
            w = [0.35, 0.65]
        self.cfg.ensemble_weights = w

    # ---------- Normalizer ----------
    def _normalize_case(self, s: str) -> str:
        s = unicodedata.normalize("NFKC", s or "")
        s = re.sub(r"\s+", " ", s).strip()
        return s.lower() if self.cfg.case_norm == "lower" else s.upper()

    @staticmethod
    def _clean_text(s: str) -> str:
        s = re.sub(r"\s+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        s = re.sub(r"[ \t]{2,}", " ", s)
        return s.strip()

    def _split_text(self, text: str) -> List[str]:
        """
        Chunk theo câu, giới hạn chunk_size (ký tự) và giữ overlap (ký tự).
        """
        chunk_size = self.cfg.chunk_size
        overlap = self.cfg.overlap

        if not text or not text.strip():
            return []

        sentences = re.split(r'(?<=[.!?。！？])\s+', text)
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue

            sent_len = len(sent)

            if current and current_len + 1 + sent_len > chunk_size:
                chunks.append(" ".join(current))

                if overlap > 0 and current:
                    kept: List[str] = []
                    total = 0
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

            if current:
                current_len += 1 + sent_len
            else:
                current_len = sent_len
            current.append(sent)

        if current:
            chunks.append(" ".join(current))

        return chunks

    # ---------- I/O TXT & corpus ----------
    def _load_txt_folder(self, folder: Optional[str] = None) -> Dict[str, str]:
        """
        Đọc toàn bộ .txt trong folder.
        - Nếu folder=None -> dùng cfg.data_dir.
        """
        data: Dict[str, str] = {}
        folder = os.path.abspath(folder or self.cfg.data_dir)
        if not os.path.isdir(folder):
            return data

        for root, _, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(".txt"):
                    file_path = os.path.join(root, fn)
                    rel_path = os.path.relpath(file_path, folder)
                    with open(file_path, "r", encoding="utf-8") as f:
                        data[rel_path] = f.read(1024 * 1024 * 10)
        return data

    def _save_corpus_jsonl(self, docs: List[Document], corpus_path: Optional[str] = None) -> None:
        """
        Handles data persistence:
        - If Pinecone: Uploads ONLY if marker file is missing (skips local jsonl).
        - If FAISS/Local: Saves to corpus.jsonl.
        """
        vectordb_type = (os.getenv("VECTORDB_TYPE", "faiss") or "faiss").strip().lower()
        corpus_path = corpus_path or self.cfg.corpus_path
        marker_path = str(corpus_path) + ".pinecone_done"

        if vectordb_type == "pinecone":
            # if os.path.exists(marker_path):
            #     print("[hybrid_retriever] ✅ Pinecone sync marker found. Skipping upload.")
            #     return

            # User requested to use Pinecone directly without managing upload/sync from here
            print("[hybrid_retriever] ⏩ Skipping upload (User manages Pinecone data). Using existing index directly.")
            
            # Upload to Pinecone - DISABLED as per user request
            # self._upload_docs_to_pinecone(docs)
            
            # Create marker file to prevent future re-uploads
            # try:
            #     os.makedirs(os.path.dirname(marker_path), exist_ok=True)
            #     with open(marker_path, "w") as f:
            #         f.write("done")
            #     print(f"[hybrid_retriever] ✅ Created sync marker: {marker_path}")
            # except Exception as e:
            #     print(f"[hybrid_retriever] ⚠️ Could not create marker file: {e}")
            return
        
        # Fallback: Save corpus.jsonl for non-Pinecone modes
        try:
            os.makedirs(os.path.dirname(corpus_path), exist_ok=True)
            with open(corpus_path, "w", encoding="utf-8") as f:
                for d in docs:
                    text = d.page_content
                    if text.lower().startswith("passage: "):
                        text = text[len("passage: "):]
                    rec = {"text": text, "metadata": d.metadata}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[hybrid_retriever] ✅ Saved valid corpus.jsonl for BM25 cache.")
        except Exception as e:
            print(f"[hybrid_retriever] ⚠️ Error saving corpus.jsonl: {e}")
    
    def _upload_docs_to_pinecone(self, docs: List[Document]) -> None:
        """Upload docs lên Pinecone thay vì lưu corpus.jsonl."""
        try:
            from langchain_pinecone import PineconeVectorStore
            from langchain_huggingface import HuggingFaceEmbeddings
            from pinecone import Pinecone
            
            api_key = os.environ.get("PINECONE_API_KEY")
            index_name = os.environ.get("PINECONE_INDEX_NAME")
            embed_model_dir = os.environ.get(
                "EMBED_MODEL_DIR",
                "intfloat/multilingual-e5-small"
            )
            
            if not api_key or not index_name:
                print("[hybrid_retriever] VECTORDB_TYPE=pinecone nhưng thiếu PINECONE_API_KEY hoặc PINECONE_INDEX_NAME → skip upload")
                return
            
            print(f"[hybrid_retriever] Uploading {len(docs)} docs lên Pinecone index '{index_name}'...")
            
            # Tạo embeddings
            device = "cuda" if torch.cuda.is_available() else "cpu"
            embeddings = HuggingFaceEmbeddings(
                model_name=embed_model_dir,
                model_kwargs={"device": device},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 64 if device == "cuda" else 16},
            )
            
            # Upload lên Pinecone
            vectorstore = PineconeVectorStore(
                index_name=index_name,
                embedding=embeddings,
            )
            vectorstore.add_documents(docs)
            print(f"[hybrid_retriever] ✅ Đã upload {len(docs)} docs lên Pinecone (bỏ qua corpus.jsonl)")
            
        except Exception as e:
            print(f"[hybrid_retriever] ⚠️ Lỗi upload Pinecone: {e} → fallback lưu corpus.jsonl")
            # Fallback: vẫn lưu corpus.jsonl nếu upload thất bại
            corpus_path = self.cfg.corpus_path
            os.makedirs(os.path.dirname(corpus_path), exist_ok=True)
            with open(corpus_path, "w", encoding="utf-8") as f:
                for d in docs:
                    text = d.page_content
                    if text.lower().startswith("passage: "):
                        text = text[len("passage: "):]
                    rec = {"text": text, "metadata": d.metadata}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _load_corpus_jsonl(self, corpus_path: Optional[str] = None) -> List[Document]:
        corpus_path = corpus_path or self.cfg.corpus_path
        if not os.path.isfile(corpus_path):
            # Check if we have raw text loaded but no jsonl (common when skipping jsonl save)
            return []


        docs: List[Document] = []
        try:
            with open(corpus_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        return []
                    meta = rec.get("metadata", {})
                    if meta.get("norm_case") != self.cfg.case_norm:
                        print(f"[hybrid_retriever] Case mismatch ({meta.get('norm_case')} != {self.cfg.case_norm}), rebuilding...")
                        return []
                    docs.append(Document(page_content=rec["text"], metadata=meta))
        except Exception as e:
            print(f"[WARN] Failed to load corpus.jsonl: {e} -> rebuild")
            return []
            
        print(f"[hybrid_retriever] Loaded {len(docs)} docs from corpus cache.")
        return docs

    # ---------- BM25 docs ----------
    def prepare_bm25_docs(
        self,
        folder: Optional[str] = None,
        corpus_path: Optional[str] = None,
    ) -> List[Document]:
        """
        1) Thử nạp corpus.jsonl sẵn có (nếu norm_case khớp).
        2) Nếu chưa có/không khớp: đọc folder .txt (mặc định cfg.data_dir),
           chuẩn hoá CASE_NORM, split chunk và lưu corpus.jsonl cho lần sau.
        """
        docs = self._load_corpus_jsonl(corpus_path)
        if docs:
            return docs

        raw = self._load_txt_folder(folder)
        out_docs: List[Document] = []
        chunk_id = 0

        for fname, text in raw.items():
            t = self._clean_text(text)
            if not t:
                continue
            t_norm = self._normalize_case(t)
            for piece in self._split_text(t_norm):
                out_docs.append(
                    Document(
                        page_content=piece,
                        metadata={
                            "page": -1,
                            "chunk_id": chunk_id,
                            "norm_case": self.cfg.case_norm,
                            "source_file": fname,
                        },
                    )
                )
                chunk_id += 1

        if out_docs:
            self._save_corpus_jsonl(out_docs, corpus_path)
        return out_docs

    # ---------- Hybrid retriever ----------
    def build_retriever(
        self,
        vs,
        folder: Optional[str] = None,
        corpus_path: Optional[str] = None,
    ) -> EnsembleRetriever:
        """
        vs: VectorStore FAISS (đã load sẵn)
        folder: folder .txt làm corpus BM25 (None -> cfg.data_dir)
        corpus_path: file corpus.jsonl (None -> cfg.corpus_path)
        """
        sem = vs.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": self.cfg.k_sem,
                "fetch_k": self.cfg.mmr_fetch_k,
                "lambda_mult": self.cfg.mmr_lambda,
            },
        )

        bm25_docs = self.prepare_bm25_docs(folder=folder, corpus_path=corpus_path)
        bm25 = BM25Retriever.from_documents(bm25_docs)
        bm25.k = self.cfg.k_lex

        ens = EnsembleRetriever(
            retrievers=[bm25, sem],
            weights=self.cfg.ensemble_weights,
        )
        return ens

    # ---------- RERANK ----------
    def _get_reranker(self) -> CrossEncoder:
        if self._reranker is None:
            with self._reranker_lock:
                if self._reranker is None:
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                    print(f"[Reranker] Loading {self.cfg.rerank_model} on {device}... (chỉ load 1 lần)")
                    self._reranker = CrossEncoder(
                        self.cfg.rerank_model,
                        device=device,
                        max_length=512,
                        activation_fn=torch.nn.Sigmoid(),
                    )
        return self._reranker

    def rerank(
        self,
        query: str,
        docs: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Tuple[Document, Optional[float]]]:
        try:
            k = int(top_k if top_k is not None else self.cfg.rerank_top_k)
        except Exception:
            k = 7

        if (not self.cfg.use_rerank) or (not docs):
            return [(d, None) for d in docs[:k]]

        if len(docs) <= k:
            return [(d, None) for d in docs[:k]]

        try:
            ce = self._get_reranker()
            pairs = [(query, d.page_content) for d in docs[: self.cfg.rerank_candidates]]
            scores = ce.predict(pairs, batch_size=64)
            ranked = sorted(
                zip(docs[: self.cfg.rerank_candidates], scores),
                key=lambda x: x[1],
                reverse=True,
            )
            result = ranked[:k]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return result
        except Exception as e:
            print(f"[Rerank lỗi] {e}")
            return [(d, None) for d in docs[:k]]


# ========================
# MODULE-LEVEL API (GIỮ TÊN CŨ)
# ========================
_DEFAULT_MANAGER = HybridRetrieverManager()


def normalize_query(q: str) -> str:
    """Giữ API cũ: chuẩn hoá query."""
    return _DEFAULT_MANAGER._normalize_case(q or "")


def prepare_bm25_docs(
    folder: Optional[str] = None,
    corpus_path: Optional[str] = None,
) -> List[Document]:
    """Giữ API cũ, dùng default manager."""
    return _DEFAULT_MANAGER.prepare_bm25_docs(folder=folder, corpus_path=corpus_path)


def build_hybrid_retriever(
    vs,
    folder: Optional[str] = None,
    corpus_path: Optional[str] = None,
) -> EnsembleRetriever:
    """
    API cũ:

        retriever = build_hybrid_retriever(vs)
t
    API mới (override folder/corpus):

        retriever = build_hybrid_retriever(
            vs,
            folder="/data/tiximax/hr_docs",
            corpus_path="/data/tiximax/faiss/hr_corpus.jsonl",
        )
    """
    return _DEFAULT_MANAGER.build_retriever(vs, folder=folder, corpus_path=corpus_path)


def rerank(
    query: str,
    docs: List[Document],
    top_k: int = RERANK_TOP_K,
) -> List[Tuple[Document, Optional[float]]]:
    """Giữ API cũ, delegate qua default manager."""
    return _DEFAULT_MANAGER.rerank(query, docs, top_k=top_k)
