import os
import os as _os
from dotenv import load_dotenv, find_dotenv

# Load .env từ CWD trở lên
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

# ---------- Helpers: đọc env với ưu tiên _HR ----------
def _env_get(keys, default=None):
    if isinstance(keys, str):
        keys = [keys]
    for k in keys:
        v = os.environ.get(k)
        if v is not None:
            return v
    return default

def _env_bool(keys, default="0"):
    v = str(_env_get(keys, default)).strip().lower()
    return v not in ("0", "false", "no", "off", "")

def _env_int(keys, default="0"):
    try:
        return int(str(_env_get(keys, default)).strip())
    except Exception:
        return int(default)

def _env_float(keys, default="0.0"):
    try:
        return float(str(_env_get(keys, default)).strip())
    except Exception:
        return float(default)

# ---------- Paths & models ----------
INDEX_DIR = resolve_path(_env_get(["INDEX_DIR_HR", "INDEX_DIR"], r"e:\Chatbot\Chatbot\vectorstore\FAISS_Vector"))
DATA_DIR  = resolve_path(_env_get(["DATA_DIR_HR",  "DATA_DIR"],  r"./src/app/Data"))
EMBED_MODEL_NAME = _env_get(["EMBED_MODEL_NAME_HR", "EMBED_MODEL_NAME"], r"./models/multilingual-e5-base")

GEMINI_MODEL_ANSWER = _env_get(["GEMINI_MODEL_ANSWER_HR", "GEMINI_MODEL_ANSWER"], "gemini-2.0-flash")
GEMINI_MODEL_JUDGE  = _env_get(["GEMINI_MODEL_JUDGE_HR",  "GEMINI_MODEL_JUDGE"],  "gemini-2.0-flash")
RERANK_MODEL        = _env_get(["RERANK_MODEL_HR", "RERANK_MODEL"], "cross-encoder/ms-marco-MiniLM-L-6-v2")

# ---------- Retrieval params ----------
TOP_K        = _env_int(["RAG_TOPK_HR", "RAG_TOPK"], "20")
K_SEM        = _env_int(["K_SEM_HR", "K_SEM"], "20")
K_LEX        = _env_int(["K_LEX_HR", "K_LEX"], "20")
MMR_FETCH_K  = _env_int(["MMR_FETCH_K_HR", "MMR_FETCH_K"], "80")
MMR_LAMBDA   = _env_float(["MMR_LAMBDA_HR", "MMR_LAMBDA"], "0.45")

USE_RERANK        = _env_bool(["USE_RERANK_HR", "USE_RERANK"], "1")
RERANK_CANDIDATES = _env_int (["RERANK_CANDIDATES_HR", "RERANK_CANDIDATES"], "80")
RERANK_TOP_K      = _env_int (["RERANK_TOP_K_HR", "RERANK_TOP_K"], str(TOP_K))

USE_BM25     = _env_bool(["USE_BM25_HR", "USE_BM25"], "1")
FAST_MODE    = _env_bool(["FAST_MODE_HR", "FAST_MODE"], "0")
ENABLE_JUDGE = _env_bool(["ENABLE_JUDGE_HR", "ENABLE_JUDGE"], "0")
METRICS      = _env_bool(["METRICS_HR", "METRICS"], "0")

# ---------- Context & formatting ----------
MAX_CHARS_CTX = _env_int(["CTX_CHARS_HR", "CTX_CHARS"], "2200")

CASE_NORM = (_env_get(["CASE_NORM_HR", "CASE_NORM"], "lower") or "lower").strip().lower()
if CASE_NORM not in ("lower", "upper"):
    CASE_NORM = "lower"

PROFILE   = (_env_get(["PROFILE_HR", "PROFILE"], "HR") or "HR").strip().upper()
HR_TONE   = (_env_get(["HR_TONE_HR", "HR_TONE"], "chuyên nghiệp, rõ ràng, súc tích") or "").strip()
HR_OUTPUT = (_env_get(["HR_OUTPUT_HR", "HR_OUTPUT"], "AUTO") or "AUTO").strip().upper()

CHAT_HISTORY_TURNS = _env_int(["CHAT_HISTORY_TURNS_HR", "CHAT_HISTORY_TURNS"], "6")
CONTINUE_RETRIEVE  = _env_bool(["CONTINUE_RETRIEVE_HR", "CONTINUE_RETRIEVE"], "0")

# ---------- BM25 corpus ----------
FAISS_DIR   = resolve_path(_env_get(["FAISS_DIR_HR", "FAISS_DIR", "INDEX_DIR_HR", "INDEX_DIR"], INDEX_DIR))
CORPUS_PATH = os.path.join(FAISS_DIR, "corpus.jsonl")

# ---------- LLM Query Rewrite ----------
USE_QR_LLM     = _env_bool(["USE_QR_LLM_HR", "USE_QR_LLM"], "1")
QR_LLM_MODEL   = _env_get (["QR_LLM_MODEL_HR", "QR_LLM_MODEL"], "gemini-2.0-flash")
QR_NUM_ALIASES = _env_int (["QR_NUM_ALIASES_HR", "QR_NUM_ALIASES"], "5")

# ---------- PRF ----------
USE_PRF           = _env_bool (["USE_PRF_HR", "USE_PRF"], "1")
PRF_K_SEM         = _env_int  (["PRF_K_SEM_HR", "PRF_K_SEM"], "6")
PRF_NGRAMS_STR    = _env_get  (["PRF_NGRAMS_HR", "PRF_NGRAMS"], "2,3,4") or "2,3,4"
PRF_NGRAMS        = [int(x) for x in PRF_NGRAMS_STR.split(",") if x.strip().isdigit()]
PRF_TOP_PHRASES   = _env_int  (["PRF_TOP_PHRASES_HR", "PRF_TOP_PHRASES"], "3")
PRF_MIN_LEN_CHARS = _env_int  (["PRF_MIN_LEN_CHARS_HR", "PRF_MIN_LEN_CHARS"], "5")

# ---------- Hybrid weighting ----------
W_SEM = _env_float(["W_SEM_HR", "W_SEM"], "0.5")
W_LEX = _env_float(["W_LEX_HR", "W_LEX"], "0.5")

# ---------- Boost lặp phrase cho BM25 ----------
PHRASE_BOOST_TIMES = _env_int(["PHRASE_BOOST_TIMES_HR", "PHRASE_BOOST_TIMES"], "2")

# ---------- Output post-process ----------
STRIP_CITATIONS = _env_bool(["STRIP_CITATIONS_HR", "STRIP_CITATIONS"], "1")

# ---------- Debug ----------
DEBUG_QE = _env_bool(["DEBUG_QE_HR", "DEBUG_QE"], "1")
