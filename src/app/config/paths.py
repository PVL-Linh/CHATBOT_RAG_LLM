import os
from pathlib import Path
from app.config.utils_config import _resolve_path

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

# Models / Embeddings / Vectorstore
MODELS_DIS = get_path("MODELS_DIR", APP_DIR / "models")
EMBED_MODEL_DIR = get_path("EMBED_MODEL_DIR", MODELS_DIS / "local_multilingual_e5_large")
EMBED_REVISION = os.environ.get("EMBED_REVISION")
EMBED_MODEL_ID = os.getenv("EMBED_MODEL_ID", "intfloat/multilingual-e5-large")

VECTORSTORE_DIR = get_path("VECTORSTORE_DIR", APP_DIR / "vectorstore")
FAISS_ALL_DIR = VECTORSTORE_DIR / "FAISS_Vector_All"
FAISS_HR_DIR_1 = VECTORSTORE_DIR / "FAISS_Vector_HR"

# INDEX HR FILE
DATA_DIR_HR_1 = get_path("DATA_DIR_HR", APP_DIR / "Data" / "HR")
DATA_DIR_HR  = _resolve_path(DATA_DIR_HR_1)
# INDEX_HR_TXT = DATA_DIR_HR / "txt"
# INDEX_HR_DIAGRAM = DATA_DIR_HR / "diagram"

FAISS_DIR_HR = _resolve_path(FAISS_HR_DIR_1 or os.environ.get("FAISS_DIR_HR"))
GEMINI_MODEL_ANSWER_HR = os.getenv("GEMINI_MODEL_ANSWER_HR", "gemini-2.0-flash")
GEMINI_MODEL_JUDGE_HR  = os.getenv("GEMINI_MODEL_JUDGE_HR", "gemini-2.0-flash")


os.makedirs(DATA_DIR, exist_ok=True)


# Marketing - Planner
PLANNER_OUTPUT_CAP = int(os.getenv("PLANNER_OUTPUT_CAP", "2048"))  
PLANNER_MINIBODY_CAP = int(os.getenv("PLANNER_MINIBODY_CAP", "600"))
PLANNER_ENDING_CAP = int(os.getenv("PLANNER_ENDING_CAP", "200"))
PLANNER_TOKEN_BOOST = float(os.getenv("PLANNER_TOKEN_BOOST", "1.10"))
PLANNER_SHORT_CAP = int(os.getenv("PLANNER_SHORT_CAP", 512))