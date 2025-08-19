import os
from dotenv import load_dotenv
import google.generativeai as genai_old
from google import genai as genai_new

load_dotenv()

API_KEY_MKT = os.getenv("GEMINI_API_KEY")
if not API_KEY_MKT:
    raise RuntimeError("Không tìm thấy GEMINI_API_KEY trong .env")

# Old SDK (text)
genai_old.configure(api_key=API_KEY_MKT)
# TEXT_MODEL_MKT = "gemini-1.5-flash"
TEXT_MODEL_MKT = "gemini-2.0-flash"
TEMPERATURE_MKT = 0.6
MAX_TOKENS_MKT = 3200
RETRY_MAX_MKT = 5

# New SDK (image)
CLIENT_MKT = genai_new.Client(api_key=API_KEY_MKT)
GEMINI_IMAGE_MODEL_MKT = "gemini-2.0-flash-preview-image-generation"  # nhanh, experimental
IMAGEN_MODEL_MKT      = "imagen-4.0-generate-preview-06-06"           # chất lượng cao

