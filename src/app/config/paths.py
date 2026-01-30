import os
from pathlib import Path
from .utils_config import _resolve_path

# Lấy thư mục gốc của dự án 
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
APP_DIR = BASE_DIR / "src" / "app"


def get_path(env_var, default_path):
    path_str = os.getenv(env_var, default_path)
    return Path(path_str) if path_str else default_path

# Data / DB -> Data_app
DATA_APP_DIR = get_path("DATA_APP_DIR", APP_DIR / "Data_app")
CHAT_LOGS_DIR = DATA_APP_DIR / "chat_logs"
USERS_CSV = DATA_APP_DIR / "users.csv"
USERS_DB = DATA_APP_DIR / "users.db"
USERS_PROMPTS = DATA_APP_DIR / "prompts.db"
USER_CHAT_HR = DATA_APP_DIR / "chat_history_hr.db"
USER_CHAT_ALL = DATA_APP_DIR / "chat_history_all.db"
CHANNELS_JSON = DATA_APP_DIR / "channels.json"
HISTORY_JSON_SAVED = DATA_APP_DIR / "saved_history_marketing.json"

# Data
DATA_DIR = get_path("DATA_DIR", APP_DIR / "Data" / "Data_All")

# Data Marketing
DB_PATH_MARKETING = os.path.join(str(DATA_APP_DIR), "saved_marketing.db")

# Uploads Videos / Audios
UPLOAD_VIDEOS_DIR = DATA_APP_DIR / "uploads" / "videos"

# pdf to text
PDF_TEXT_DIR = DATA_APP_DIR / "pdf_to_text"
PDF_TMP_DIR = DATA_APP_DIR / "pdf_tmp"

# WAREHOUSE
DATA_DIR_WAREHOUSE = get_path("DATA_DIR_WAREHOUSE", APP_DIR / "Data" / "WAREHOUSE")

# SALES
DATA_DIR_SALES = get_path("DATA_DIR_SALES", APP_DIR / "Data" / "Sales")

# Models / Embeddings / Vectorstore
MODELS_DIS = get_path("MODELS_DIR", APP_DIR / "models")
EMBED_MODEL_DIR = get_path("EMBED_MODEL_DIR", "intfloat/multilingual-e5-small")
EMBED_REVISION = os.environ.get("EMBED_REVISION")
EMBED_MODEL_ID = os.getenv("EMBED_MODEL_ID", "intfloat/multilingual-e5-small")

VECTORSTORE_DIR = get_path("VECTORSTORE_DIR", APP_DIR / "vectorstore")
FAISS_ALL_DIR = VECTORSTORE_DIR / "FAISS_Vector_Data_All"
FAISS_HR_DIR_1 = VECTORSTORE_DIR / "FAISS_Vector_HR"
FAISS_ALL_DIR_WAREHOUSE = VECTORSTORE_DIR / "FAISS_Vector_WAREHOUSE"
FAISS_ALL_DIR_SALES = VECTORSTORE_DIR / "FAISS_Vector_SALES"

# INDEX HR FILE
DATA_DIR_HR_1 = get_path("DATA_DIR_HR", APP_DIR / "Data" / "HR")
DATA_DIR_HR  = _resolve_path(DATA_DIR_HR_1)
FAISS_DIR_HR = _resolve_path(FAISS_HR_DIR_1 or os.environ.get("FAISS_DIR_HR"))
GEMINI_MODEL_ANSWER_HR = os.getenv("GEMINI_MODEL_ANSWER_HR", "gemma-3-4b-it")
GEMINI_MODEL_JUDGE_HR  = os.getenv("GEMINI_MODEL_JUDGE_HR", "gemma-3-4b-it")

# INDEX ACCOUNTANT FILE
FAISS_ACCOUNTANT_DIR_1 = VECTORSTORE_DIR / "FAISS_Vector_Accountant"

DATA_DIR_ACCOUNTANT_1 = get_path("DATA_DIR_ACCOUNTANT", APP_DIR / "Data" / "Accountant")
DATA_DIR_ACCOUNTANT  = _resolve_path(DATA_DIR_ACCOUNTANT_1)
FAISS_DIR_ACCOUNTANT = _resolve_path(FAISS_ACCOUNTANT_DIR_1 or os.environ.get("FAISS_DIR_Accountant"))
GEMINI_MODEL_ANSWER_ACCOUNTANT = os.getenv("GEMINI_MODEL_ANSWER_ACCOUNTANT", "gemma-3-4b-it")
GEMINI_MODEL_JUDGE_ACCOUNTANT  = os.getenv("GEMINI_MODEL_JUDGE_ACCOUNTANT", "gemma-3-4b-it")

os.makedirs(DATA_DIR, exist_ok=True)


# Marketing - Planner
PLANNER_OUTPUT_CAP = int(os.getenv("PLANNER_OUTPUT_CAP", "2048"))  
PLANNER_MINIBODY_CAP = int(os.getenv("PLANNER_MINIBODY_CAP", "600"))
PLANNER_ENDING_CAP = int(os.getenv("PLANNER_ENDING_CAP", "200"))
PLANNER_TOKEN_BOOST = float(os.getenv("PLANNER_TOKEN_BOOST", "1.10"))
PLANNER_SHORT_CAP = int(os.getenv("PLANNER_SHORT_CAP", 512))

# upload file
UPLOAD_DIR = APP_DIR / "uploads"