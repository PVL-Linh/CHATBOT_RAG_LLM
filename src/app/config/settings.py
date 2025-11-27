import os
import threading
from .paths import FAISS_ALL_DIR
from dotenv import load_dotenv
load_dotenv()
class ChatConfig:
    LLM_SEM = threading.Semaphore(int(os.environ.get("SEM_LLM", 24)))
    MAX_HISTORY = int(os.environ.get("MAX_HISTORY", 100))
    LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

# app_factory.py
class AppConfig:
    ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-in-production")

    # Upload / json 
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = False
    PREFERRED_URL_SCHEME = "https"

    # App version
    APP_VERSION = "1.0.0"
    

class Chat_HR:
    EMBED_MODEL_NAME_HR = os.getenv("EMBED_MODEL_NAME_HR", "intfloat/multilingual-e5-base")
    HR_TONE = os.getenv("HR_TONE", "chuyên nghiệp, rõ ràng, súc tích")
    HR_OUTPUT = os.getenv("HR_OUTPUT", "AUTO")
    RAG_TOPK_HR = int(os.getenv("RAG_TOPK_HR", 40))
    USE_RERANK_HR = os.getenv("USE_RERANK_HR", "1") == "1"
    GEMINI_MODEL_ANSWER_HR = os.environ.get("GEMINI_MODEL_ANSWER_HR", "gemini-2.0-flash")
    GEMINI_MODEL_JUDGE_HR  = os.environ.get("GEMINI_MODEL_JUDGE_HR",  "gemini-2.0-flash")


class hybrid_retriever:
    TOP_K = int(os.environ.get("TOP_K", "14") or "14")
    K_SEM = int(os.environ.get("K_SEM", "16") or "16")
    K_LEX = int(os.environ.get("K_LEX", "18") or "18")
    MMR_FETCH_K = int(os.environ.get("MMR_FETCH_K", "60") or "60")
    MMR_LAMBDA = float(os.environ.get("MMR_LAMBDA", "0.6") or "0.6")
    USE_RERANK = os.environ.get("USE_RERANK", "True").lower() in ("true", "1", "yes", "on")
    RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES", "70") or "70")
    RERANK_MODEL = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

try:
    _rerank_default = os.environ.get("RERANK_TOP_K") or os.environ.get("TOP_K") or str(hybrid_retriever.TOP_K) or "14"
    hybrid_retriever.RERANK_TOP_K = int(_rerank_default)
except ValueError:
    hybrid_retriever.RERANK_TOP_K = 14 

class Chat_engine:
    DB_CONF_THRESHOLD = float(os.environ.get("DB_CONF_THRESHOLD", "0.65"))
    REWRITE_DB_WITH_LLM = os.environ.get("REWRITE_DB_WITH_LLM", "1").strip() not in {
        "0",
        "false",
        "False",
    }

class Gemini_Config_LLM:
    token = os.environ.get("HF_TOKEN")
    force = (os.environ.get("HF_FORCE_DOWNLOAD", "0").strip().lower() == "1")
    api_key = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")
    api_url = os.getenv("HUGGINGFACEHUB_API_URL") or "https://api-inference.huggingface.co/models"
    repo_type = os.environ.get("FAISS_HUB_REPO_TYPE", "dataset")
    # Mặc định dùng tên thư mục FAISS thực tế (FAISS_ALL_DIR.name = "FAISS_Vector_All")
    subdir = os.getenv("FAISS_HUB_SUBDIR", FAISS_ALL_DIR.name).strip().strip("/")