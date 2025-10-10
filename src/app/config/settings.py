import os
import threading
from .paths import FAISS_ALL_DIR


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
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
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
    TOP_K = os.environ.get("TOP_K", 22)
    K_SEM = os.environ.get("K_SEM", 20)
    K_LEX = os.environ.get("K_LEX", 20)
    MMR_FETCH_K = os.environ.get("MMR_FETCH_K", 80)
    MMR_LAMBDA = os.environ.get("MMR_LAMBDA", 0.45)

    USE_RERANK = os.environ.get("USE_RERANK", "True").lower() == "true"
    RERANK_CANDIDATES = os.environ.get("RERANK_CANDIDATES", 80)
    RERANK_TOP_K = os.environ.get("RERANK_TOP_K", TOP_K)
    RERANK_MODEL = os.environ.get("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2") # BAAI/bge-reranker-v2-m3


class Gemini_Config_LLM:
    token = os.environ.get("HF_TOKEN")
    force = (os.environ.get("HF_FORCE_DOWNLOAD", "0").strip().lower() == "1")
    api_key = os.getenv("HUGGINGFACEHUB_API_TOKEN") or os.getenv("HF_TOKEN")
    api_url = os.getenv("HUGGINGFACEHUB_API_URL") or "https://api-inference.huggingface.co/models"
    repo_type = os.environ.get("FAISS_HUB_REPO_TYPE", "dataset")
    # Mặc định dùng tên thư mục FAISS thực tế (FAISS_ALL_DIR.name = "FAISS_Vector_All")
    subdir = os.getenv("FAISS_HUB_SUBDIR", FAISS_ALL_DIR.name).strip().strip("/")