# -*- coding: utf-8 -*-
import os
from app.config.utils_config import _env_get, _env_bool, _env_int, _env_float, _resolve_path
from app.config.paths import *
# from dotenv import load_dotenv
# load_dotenv()
# ---------- retrieval ----------
RAG_TOPK_HR   = _env_int ("RAG_TOPK_HR",   "40")
K_SEM_HR      = _env_int ("K_SEM_HR",      "20")
K_LEX_HR      = _env_int ("K_LEX_HR",      "20")
MMR_FETCH_K_HR= _env_int ("MMR_FETCH_K_HR","80")
MMR_LAMBDA_HR = _env_float("MMR_LAMBDA_HR","0.45")
USE_BM25_HR   = _env_bool ("USE_BM25_HR",  "1")
FAST_MODE_HR  = _env_bool ("FAST_MODE_HR", "0")

# ---------- weights ----------
W_SEM_HR = _env_float("W_SEM_HR", "0.5")
W_LEX_HR = _env_float("W_LEX_HR", "0.5")

# ---------- rerank ----------
USE_RERANK_HR        = _env_bool ("USE_RERANK_HR", "1")
RERANK_MODEL_HR      = _env_get  ("RERANK_MODEL_HR", "cross-encoder/ms-marco-MiniLM-L-12-v2")
RERANK_CANDIDATES_HR = _env_int  ("RERANK_CANDIDATES_HR", "80")
RERANK_TOP_K_HR      = _env_int  ("RERANK_TOP_K_HR", str(RAG_TOPK_HR))

# ---------- context ----------
MAX_CHARS_CTX_HR = _env_int("CTX_CHARS_HR", "6000")
CASE_NORM_HR     = (_env_get("CASE_NORM_HR", "lower") or "lower").strip().lower()
if CASE_NORM_HR not in ("lower", "upper"):
    CASE_NORM_HR = "lower"

PROFILE_HR   = (_env_get("PROFILE_HR","HR") or "HR").strip().upper()
HR_TONE      = _env_get("HR_TONE", "chuyên nghiệp, rõ ràng, súc tích").strip()
HR_OUTPUT    = (_env_get("HR_OUTPUT","AUTO") or "AUTO").strip().upper()

# ---------- registry ----------
SOURCE_REGISTRY_PATH = _resolve_path(_env_get("SOURCE_REGISTRY_PATH","./src/app/Data/doc_catalog.json"))
STRICT_SOURCE_MATCH_HR = _env_bool("STRICT_SOURCE_MATCH_HR","1")
ORG_SOURCE_HINT_HR = _env_get("ORG_SOURCE_HINT_HR","").strip()


# QE
USE_QR_LLM_HR     = _env_bool ("USE_QR_LLM_HR", "1")
QR_LLM_MODEL_HR   = _env_get  ("QR_LLM_MODEL_HR","gemini-2.5-flash")
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

# misc
STRIP_CITATIONS_HR = _env_bool("STRIP_CITATIONS_HR","1")
METRICS_HR         = _env_bool("METRICS_HR","0")
DEBUG_QE_HR        = _env_bool("DEBUG_QE_HR","1")

# Backward-compat
TOP_K_HR = RAG_TOPK_HR
MAX_CHARS_CTX = MAX_CHARS_CTX_HR
CASE_NORM = CASE_NORM_HR
