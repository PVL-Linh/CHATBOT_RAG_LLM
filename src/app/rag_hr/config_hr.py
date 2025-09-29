import os
import os as _os
from dotenv import load_dotenv, find_dotenv

# Load .env from CWD upward
_DOTENV_PATH = os.getenv("DOTENV_PATH") or find_dotenv(usecwd=True)
if _DOTENV_PATH:
    load_dotenv(_DOTENV_PATH, override=False)

def resolve_path(p: str) -> str:
    if not p:
        return p
    if _os.path.isabs(p):
        return p
    base = _os.path.dirname(_DOTENV_PATH) if _DOTENV_PATH else _os.getcwd()
    return _os.path.abspath(_os.path.join(base, p))

# Paths & models
INDEX_DIR = resolve_path(os.environ.get("INDEX_DIR_HR", r"e:\Chatbot\Chatbot\vectorstore\FAISS_Vector"))
DATA_DIR  = resolve_path(os.environ.get("DATA_DIR_HR",  r"./src/app/Data"))
EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_NAME_HR", r"./models/multilingual-e5-base")

GEMINI_MODEL_ANSWER = os.environ.get("GEMINI_MODEL_ANSWER_HR", "gemini-2.0-flash")
GEMINI_MODEL_JUDGE  = os.environ.get("GEMINI_MODEL_JUDGE_HR",  "gemini-2.0-flash")
RERANK_MODEL        = os.environ.get("RERANK_MODEL_HR", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Retrieval params
TOP_K = int(os.environ.get("RAG_TOPK_HR", "20"))
K_SEM = int(os.environ.get("K_SEM_HR", "20"))
K_LEX = int(os.environ.get("K_LEX_HR", "20"))
MMR_FETCH_K = int(os.environ.get("MMR_FETCH_K_HR", "80"))
MMR_LAMBDA  = float(os.environ.get("MMR_LAMBDA_HR", "0.45"))

USE_RERANK        = os.environ.get("USE_RERANK_HR", "1").strip().lower() not in ("0", "false")
RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES_HR", "80"))
RERANK_TOP_K      = int(os.environ.get("RERANK_TOP_K_HR", str(TOP_K)))

USE_BM25     = os.environ.get("USE_BM25_HR", "1").strip().lower() not in ("0", "false")
FAST_MODE    = os.environ.get("FAST_MODE_HR", "0").strip().lower() not in ("0", "false")
ENABLE_JUDGE = os.environ.get("ENABLE_JUDGE_HR", "0").strip().lower() not in ("0", "false")
METRICS      = os.environ.get("METRICS_HR", "0").strip().lower() not in ("0", "false")

MAX_CHARS_CTX = int(os.environ.get("CTX_CHARS_HR", "2200"))

CASE_NORM = os.environ.get("CASE_NORM_HR", "lower").strip().lower()
if CASE_NORM not in ("lower", "upper"):
    CASE_NORM = "lower"

PROFILE   = os.environ.get("PROFILE_HR", "HR").strip().upper()
HR_TONE   = os.environ.get("HR_TONE", "chuyên nghiệp, rõ ràng, súc tích").strip()
HR_OUTPUT = os.environ.get("HR_OUTPUT", "AUTO").strip().upper()  # AUTO | JD | CHECKLIST | SOP | POLICY | TABLE

CHAT_HISTORY_TURNS = int(os.environ.get("CHAT_HISTORY_TURNS_HR", "6"))
CONTINUE_RETRIEVE  = os.environ.get("CONTINUE_RETRIEVE_HR", "0").strip().lower() not in ("0", "false")

# BM25 corpus colocated with FAISS dir
FAISS_DIR = resolve_path(os.environ.get("FAISS_DIR_HR", INDEX_DIR))
CORPUS_PATH = os.path.join(FAISS_DIR, "corpus.jsonl")
