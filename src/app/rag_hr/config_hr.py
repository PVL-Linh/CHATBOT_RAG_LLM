import os
from dotenv import load_dotenv, find_dotenv

# Load .env (GHI ĐÈ để tránh dính env cũ từ hệ điều hành)
_DOTENV_PATH = os.getenv("DOTENV_PATH") or find_dotenv(usecwd=True)
if _DOTENV_PATH:
    load_dotenv(_DOTENV_PATH, override=True)

def resolve_path(p: str) -> str:
    import os as _os
    if not p:
        return p
    if _os.path.isabs(p):
        return p
    base = _os.path.dirname(_DOTENV_PATH) if _DOTENV_PATH else _os.getcwd()
    return _os.path.abspath(_os.path.join(base, p))

# === HR-only config (không fallback sang biến không _HR) ===
INDEX_DIR_HR = resolve_path(os.environ.get("INDEX_DIR_HR", "./src/app/vectorstore/FAISS_Vector_HR"))
DATA_DIR_HR  = resolve_path(os.environ.get("DATA_DIR_HR",  "./src/app/Data/HR"))
FAISS_DIR_HR = resolve_path(os.environ.get("FAISS_DIR_HR", INDEX_DIR_HR))

EMBED_MODEL_NAME_HR = os.environ.get("EMBED_MODEL_NAME_HR", "./src/app/models/local_multilingual_e5_base")

GEMINI_MODEL_ANSWER_HR = os.environ.get("GEMINI_MODEL_ANSWER_HR", "gemini-2.0-flash")
GEMINI_MODEL_JUDGE_HR  = os.environ.get("GEMINI_MODEL_JUDGE_HR",  "gemini-2.0-flash")

TOP_K_HR       = int(os.environ.get("RAG_TOPK_HR", "20"))
K_SEM_HR       = int(os.environ.get("K_SEM_HR", "20"))
K_LEX_HR       = int(os.environ.get("K_LEX_HR", "20"))
MMR_FETCH_K_HR = int(os.environ.get("MMR_FETCH_K_HR", "80"))
MMR_LAMBDA_HR  = float(os.environ.get("MMR_LAMBDA_HR", "0.45"))

USE_RERANK_HR        = os.environ.get("USE_RERANK_HR", "1").lower() not in ("0", "false")
RERANK_CANDIDATES_HR = int(os.environ.get("RERANK_CANDIDATES_HR", "80"))
RERANK_TOP_K_HR      = int(os.environ.get("RERANK_TOP_K_HR", str(TOP_K_HR)))
RERANK_MODEL_HR      = os.environ.get("RERANK_MODEL_HR", "cross-encoder/ms-marco-MiniLM-L-12-v2")

USE_BM25_HR     = os.environ.get("USE_BM25_HR", "1").lower() not in ("0", "false")
FAST_MODE_HR    = os.environ.get("FAST_MODE_HR", "0").lower() not in ("0", "false")
ENABLE_JUDGE_HR = os.environ.get("ENABLE_JUDGE_HR", "0").lower() not in ("0", "false")
METRICS_HR      = os.environ.get("METRICS_HR", "0").lower() not in ("0", "false")

MAX_CHARS_CTX_HR = int(os.environ.get("CTX_CHARS_HR", "2200"))


CASE_NORM_HR = os.environ.get("CASE_NORM_HR", "lower").strip().lower()
if CASE_NORM_HR not in ("lower", "upper"):
    CASE_NORM_HR = "lower"

PROFILE_HR   = os.environ.get("PROFILE_HR", "HR").strip().upper()
HR_TONE      = os.environ.get("HR_TONE", "chuyên nghiệp, rõ ràng, súc tích").strip()
HR_OUTPUT    = os.environ.get("HR_OUTPUT", "AUTO").strip().upper()

CHAT_HISTORY_TURNS_HR = int(os.environ.get("CHAT_HISTORY_TURNS_HR", "6"))
CONTINUE_RETRIEVE_HR  = os.environ.get("CONTINUE_RETRIEVE_HR", "0").lower() not in ("0", "false")

# Query rewrite / PRF
def _env_bool(keys, default="0"):
    for k in keys:
        if k in os.environ:
            return os.environ[k].lower() not in ("0","false","no")
    return default.lower() not in ("0","false","no")

def _env_int(keys, default="0"):
    for k in keys:
        if k in os.environ:
            try: return int(os.environ[k])
            except: break
    return int(default)

def _env_float(keys, default="0"):
    for k in keys:
        if k in os.environ:
            try: return float(os.environ[k])
            except: break
    return float(default)

def _env_get(keys, default=""):
    for k in keys:
        if k in os.environ:
            return os.environ[k]
    return default

USE_QR_LLM_HR     = _env_bool (["USE_QR_LLM_HR","USE_QR_LLM"], "1")
QR_LLM_MODEL_HR   = _env_get  (["QR_LLM_MODEL_HR","QR_LLM_MODEL"], "gemini-2.0-flash")
QR_NUM_ALIASES_HR = _env_int  (["QR_NUM_ALIASES_HR","QR_NUM_ALIASES"], "5")

USE_PRF_HR           = _env_bool(["USE_PRF_HR","USE_PRF"], "1")
PRF_K_SEM_HR         = _env_int (["PRF_K_SEM_HR","PRF_K_SEM"], "6")
PRF_NGRAMS_STR       = _env_get (["PRF_NGRAMS_HR","PRF_NGRAMS"], "2,3,4")
PRF_NGRAMS_HR        = [int(x) for x in PRF_NGRAMS_STR.split(",") if x.strip().isdigit()]
PRF_TOP_PHRASES_HR   = _env_int (["PRF_TOP_PHRASES_HR","PRF_TOP_PHRASES"], "3")
PRF_MIN_LEN_CHARS_HR = _env_int (["PRF_MIN_LEN_CHARS_HR","PRF_MIN_LEN_CHARS"], "5")

W_SEM_HR = _env_float(["W_SEM_HR","W_SEM"], "0.5")
W_LEX_HR = _env_float(["W_LEX_HR","W_LEX"], "0.5")

PHRASE_BOOST_TIMES_HR = _env_int(["PHRASE_BOOST_TIMES_HR","PHRASE_BOOST_TIMES"], "2")

FORM_FULLCOPY_HR = _env_bool(["FORM_FULLCOPY_HR"], "1")
STRIP_CITATIONS_HR = _env_bool(["STRIP_CITATIONS_HR"], "1")
DEBUG_QE_HR = _env_bool(["DEBUG_QE_HR"], "1")

ORG_FULLCOPY_HR    = _env_bool(["ORG_FULLCOPY_HR"], "1")

# Log cấu hình chính (hữu ích để chắc chắn không bị trỏ sang FAISS_Vector_All)
print("[CFG] DOTENV_PATH     =", _DOTENV_PATH)
print("[CFG] INDEX_DIR_HR    =", INDEX_DIR_HR)
print("[CFG] FAISS_DIR_HR    =", FAISS_DIR_HR)
print("[CFG] DATA_DIR_HR     =", DATA_DIR_HR)
