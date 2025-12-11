# -*- coding: utf-8 -*-
import os
from app.config.utils_config import _env_get, _env_bool, _env_int, _env_float, _resolve_path
from app.config.paths import *
# from dotenv import load_dotenv
# load_dotenv()
# ---------- retrieval ----------
RAG_TOPK_ACCOUNTANT   = _env_int ("RAG_TOPK_ACCOUNTANT",   "20")
K_SEM_ACCOUNTANT      = _env_int ("K_SEM_ACCOUNTANT",      "20")
K_LEX_ACCOUNTANT      = _env_int ("K_LEX_ACCOUNTANT",      "20")
MMR_FETCH_K_ACCOUNTANT= _env_int ("MMR_FETCH_K_ACCOUNTANT","80")
MMR_LAMBDA_ACCOUNTANT = _env_float("MMR_LAMBDA_ACCOUNTANT","0.45")
USE_BM25_ACCOUNTANT   = _env_bool ("USE_BM25_ACCOUNTANT",  "1")
FAST_MODE_ACCOUNTANT  = _env_bool ("FAST_MODE_ACCOUNTANT", "0")

# ---------- weights ----------s
W_SEM_ACCOUNTANT = _env_float("W_SEM_ACCOUNTANT", "0.5")
W_LEX_ACCOUNTANT = _env_float("W_LEX_ACCOUNTANT", "0.5")

# ---------- rerank ----------
USE_RERANK_ACCOUNTANT        = _env_bool ("USE_RERANK_ACCOUNTANT", "1")
RERANK_MODEL_ACCOUNTANT      = _env_get  ("RERANK_MODEL_HR", "cross-encoder/ms-marco-MiniLM-L-12-v2")
RERANK_CANDIDATES_ACCOUNTANT = _env_int  ("RERANK_CANDIDATES_ACCOUNTANT", "80")
RERANK_TOP_K_ACCOUNTANT      = _env_int  ("RERANK_TOP_K_ACCOUNTANT", str(RAG_TOPK_ACCOUNTANT))

# ---------- context ----------
MAX_CHARS_CTX_ACCOUNTANT = _env_int("CTX_CHARS_ACCOUNTANT", "6000")
CASE_NORM_ACCOUNTANT     = (_env_get("CASE_NORM_ACCOUNTANT", "lower") or "lower").strip().lower()
if CASE_NORM_ACCOUNTANT not in ("lower", "upper"):
    CASE_NORM_ACCOUNTANT = "lower"

PROFILE_ACCOUNTANT   = (_env_get("PROFILE_ACCOUNTANT","ACCOUNTANT") or "Accountant").strip().upper()
ACCOUNTANT_TONE = _env_get(
    "ACCOUNTANT_TONE",
    "chuẩn mực kế toán, chuyên nghiệp, trung lập, súc tích, dựa trên số liệu, không suy đoán"
).strip()

ACCOUNTANT_OUTPUT    = (_env_get("ACCOUNTANT_OUTPUT","AUTO") or "AUTO").strip().upper()

# ---------- registry ----------
SOURCE_REGISTRY_PATH = _resolve_path(_env_get("SOURCE_REGISTRY_PATH","./src/app/Data/doc_catalog.json"))
STRICT_SOURCE_MATCH_ACCOUNTANT = _env_bool("STRICT_SOURCE_MATCH_ACCOUNTANT","1")
ORG_SOURCE_HINT_ACCOUNTANT = _env_get("ORG_SOURCE_HINT_ACCOUNTANT","").strip()


# QE
USE_QR_LLM_ACCOUNTANT     = _env_bool ("USE_QR_LLM_ACCOUNTANT", "1")
QR_LLM_MODEL_ACCOUNTANT   = _env_get  ("QR_LLM_MODEL_ACCOUNTANT","gemma-3-4b-it")
QR_NUM_ALIASES_ACCOUNTANT = _env_int  ("QR_NUM_ALIASES_ACCOUNTANT","5")

USE_PRF_ACCOUNTANT            = _env_bool ("USE_PRF_ACCOUNTANT","1")
PRF_K_SEM_ACCOUNTANT          = _env_int  ("PRF_K_SEM_ACCOUNTANT","6")
PRF_NGRAMS_ACCOUNTANT         = [int(x) for x in (_env_get("PRF_NGRAMS_ACCOUNTANT","2,3,4") or "2,3,4").split(",") if x.strip().isdigit()]
PRF_TOP_PHRASES_ACCOUNTANT    = _env_int  ("PRF_TOP_PHRASES_ACCOUNTANT","3")
PRF_MIN_LEN_CHARS_ACCOUNTANT  = _env_int  ("PRF_MIN_LEN_CHARS_ACCOUNTANT","5")
PHRASE_BOOST_TIMES_ACCOUNTANT = _env_int  ("PHRASE_BOOST_TIMES_ACCOUNTANT","2")

# full-copy & mini llm
ORG_FULLCOPY_ACCOUNTANT  = _env_bool("ORG_FULLCOPY_ACCOUNTANT","0")
JD_FULLCOPY_ACCOUNTANT   = _env_bool("JD_FULLCOPY_ACCOUNTANT","0")
FORM_FULLCOPY_ACCOUNTANT = _env_bool("FORM_FULLCOPY_ACCOUNTANT","0")

MINI_LLM_ON_FULLCOPY_ACCOUNTANT = _env_bool("MINI_LLM_ON_FULLCOPY_ACCOUNTANT","0")
MINI_LLM_TASK_ACCOUNTANT        = _env_get ("MINI_LLM_TASK_ACCOUNTANT","prefix_summary")
MINI_LLM_TASK_ORG_ACCOUNTANT    = _env_get ("MINI_LLM_TASK_ORG_ACCOUNTANT","ascii_tree")
MINI_LLM_MAXTOK_ACCOUNTANT      = _env_int ("MINI_LLM_MAXTOK_ACCOUNTANT","220")

# misc
STRIP_CITATIONS_ACCOUNTANT = _env_bool("STRIP_CITATIONS_ACCOUNTANT","1")
METRICS_ACCOUNTANT         = _env_bool("METRICS_ACCOUNTANT","0")
DEBUG_QE_ACCOUNTANT        = _env_bool("DEBUG_QE_ACCOUNTANT","1")

# Backward-compat
TOP_K_ACCOUNTANT = RAG_TOPK_ACCOUNTANT
MAX_CHARS_CTX = MAX_CHARS_CTX_ACCOUNTANT
CASE_NORM = CASE_NORM_ACCOUNTANT
