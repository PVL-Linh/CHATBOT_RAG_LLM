import os
from dotenv import load_dotenv, find_dotenv

# ---------- dotenv ----------
_DOTENV_PATH = os.getenv("DOTENV_PATH") or find_dotenv(usecwd=True)
if _DOTENV_PATH:
    load_dotenv(_DOTENV_PATH, override=False)

# ---------- helpers ----------
import os as _os
def resolve_path(p: str) -> str:
    if not p: return p
    if _os.path.isabs(p): return p
    base = _os.path.dirname(_DOTENV_PATH) if _DOTENV_PATH else _os.getcwd()
    return _os.path.abspath(_os.path.join(base, p))

def _env_get(keys, default=None):
    if isinstance(keys, (list, tuple)):
        for k in keys:
            v = os.environ.get(k)
            if v is not None: return v
        return default
    return os.environ.get(keys, default)

def _env_bool(keys, default="0"):
    v = (_env_get(keys, default) or "").strip().lower()
    return v not in ("0", "false", "no", "")

def _env_int(keys, default="0"):
    try: return int(_env_get(keys, default))
    except: return int(default)

def _env_float(keys, default="0.0"):
    try: return float(_env_get(keys, default))
    except: return float(default)

# ---------- paths / models ----------
INDEX_DIR_HR = resolve_path(os.environ.get("INDEX_DIR_HR", "./src/app/vectorstore/FAISS_Vector_HR"))
DATA_DIR_HR  = resolve_path(os.environ.get("DATA_DIR_HR",  "./src/app/Data/HR"))
FAISS_DIR_HR = resolve_path(os.environ.get("FAISS_DIR_HR", INDEX_DIR_HR))
EMBED_MODEL_NAME_HR = os.environ.get("EMBED_MODEL_NAME_HR", "./src/app/models/local_multilingual_e5_base")

GEMINI_MODEL_ANSWER_HR = os.environ.get("GEMINI_MODEL_ANSWER_HR", "gemini-2.0-flash")
GEMINI_MODEL_JUDGE_HR  = os.environ.get("GEMINI_MODEL_JUDGE_HR",  "gemini-2.0-flash")

# ---------- retrieval ----------
RAG_TOPK_HR   = _env_int ("RAG_TOPK_HR",   "20")
K_SEM_HR      = _env_int ("K_SEM_HR",      "20")
K_LEX_HR      = _env_int ("K_LEX_HR",      "20")
MMR_FETCH_K_HR= _env_int ("MMR_FETCH_K_HR","80")
MMR_LAMBDA_HR = _env_float("MMR_LAMBDA_HR","0.45")
USE_BM25_HR   = _env_bool ("USE_BM25_HR",  "1")
FAST_MODE_HR  = _env_bool ("FAST_MODE_HR", "0")

# weights WRRF
W_SEM_HR = _env_float("W_SEM_HR", "0.5")
W_LEX_HR = _env_float("W_LEX_HR", "0.5")

# rerank
USE_RERANK_HR        = _env_bool ("USE_RERANK_HR", "1")
RERANK_MODEL_HR      = _env_get  ("RERANK_MODEL_HR", "cross-encoder/ms-marco-MiniLM-L-12-v2")
RERANK_CANDIDATES_HR = _env_int  ("RERANK_CANDIDATES_HR", "80")
RERANK_TOP_K_HR      = _env_int  ("RERANK_TOP_K_HR",      str(RAG_TOPK_HR))

# context
MAX_CHARS_CTX_HR = _env_int("CTX_CHARS_HR", "2200")
CASE_NORM_HR     = (_env_get("CASE_NORM_HR", "lower") or "lower").strip().lower()
if CASE_NORM_HR not in ("lower","upper"): CASE_NORM_HR = "lower"

PROFILE_HR   = (_env_get("PROFILE_HR","HR") or "HR").strip().upper()
HR_TONE      = _env_get("HR_TONE", "chuyên nghiệp, rõ ràng, súc tích").strip()
HR_OUTPUT    = (_env_get("HR_OUTPUT","AUTO") or "AUTO").strip().upper()

# QE
USE_QR_LLM_HR     = _env_bool ("USE_QR_LLM_HR", "1")
QR_LLM_MODEL_HR   = _env_get  ("QR_LLM_MODEL_HR","gemini-2.0-flash")
QR_NUM_ALIASES_HR = _env_int  ("QR_NUM_ALIASES_HR","5")

USE_PRF_HR            = _env_bool ("USE_PRF_HR","1")
PRF_K_SEM_HR          = _env_int  ("PRF_K_SEM_HR","6")
PRF_NGRAMS_HR         = [int(x) for x in (_env_get("PRF_NGRAMS_HR","2,3,4") or "2,3,4").split(",") if x.strip().isdigit()]
PRF_TOP_PHRASES_HR    = _env_int  ("PRF_TOP_PHRASES_HR","3")
PRF_MIN_LEN_CHARS_HR  = _env_int  ("PRF_MIN_LEN_CHARS_HR","5")
PHRASE_BOOST_TIMES_HR = _env_int  ("PHRASE_BOOST_TIMES_HR","2")

# full-copy & mini llm
ORG_FULLCOPY_HR  = _env_bool("ORG_FULLCOPY_HR","1")
JD_FULLCOPY_HR   = _env_bool("JD_FULLCOPY_HR","1")
FORM_FULLCOPY_HR = _env_bool("FORM_FULLCOPY_HR","1")

MINI_LLM_ON_FULLCOPY_HR = _env_bool("MINI_LLM_ON_FULLCOPY_HR","1")
MINI_LLM_TASK_HR        = _env_get ("MINI_LLM_TASK_HR","prefix_summary")
MINI_LLM_TASK_ORG_HR    = _env_get ("MINI_LLM_TASK_ORG_HR","ascii_tree")
MINI_LLM_MAXTOK_HR      = _env_int ("MINI_LLM_MAXTOK_HR","220")

# registry / strict
SOURCE_REGISTRY_PATH = resolve_path(_env_get("SOURCE_REGISTRY_PATH","./src/app/Data/doc_catalog.json"))
STRICT_SOURCE_MATCH_HR = _env_bool("STRICT_SOURCE_MATCH_HR","1")
ORG_SOURCE_HINT_HR = _env_get("ORG_SOURCE_HINT_HR","").strip()

# misc
STRIP_CITATIONS_HR = _env_bool("STRIP_CITATIONS_HR","1")
METRICS_HR         = _env_bool("METRICS_HR","0")
DEBUG_QE_HR        = _env_bool("DEBUG_QE_HR","1")

# ---------- retrieval ----------
RAG_TOPK_HR   = _env_int ("RAG_TOPK_HR",   "20")
K_SEM_HR      = _env_int ("K_SEM_HR",      "20")
K_LEX_HR      = _env_int ("K_LEX_HR",      "20")
MMR_FETCH_K_HR= _env_int ("MMR_FETCH_K_HR","80")
MMR_LAMBDA_HR = _env_float("MMR_LAMBDA_HR","0.45")
USE_BM25_HR   = _env_bool ("USE_BM25_HR",  "1")
FAST_MODE_HR  = _env_bool ("FAST_MODE_HR", "0")

# Backward-compat cho các module cũ:
TOP_K_HR = RAG_TOPK_HR