import os
import threading

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