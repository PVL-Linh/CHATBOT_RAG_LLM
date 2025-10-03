import os, time, random
from dotenv import load_dotenv
import google.generativeai as genai_old
from google import genai as genai_new

load_dotenv()

API_KEY_MKT_FB = os.getenv("GEMINI_API_KEY_FB")
if not API_KEY_MKT_FB:
    raise RuntimeError("Không tìm thấy GEMINI_API_KEY trong .env")

# =========================
# Free-only switch
# =========================
FREE_ONLY = os.getenv("GEMINI_FREE_ONLY", "1") == "1"  # 1 = chỉ dùng model free

# =========================
# TEXT (Old SDK) — FREE
# =========================
genai_old.configure(api_key=API_KEY_MKT_FB)

TEXT_MODEL_MKT_FB  = os.getenv("GEMINI_TEXT_MODEL_FB", "gemini-2.5-flash")  # FREE
TEMPERATURE_MKT = float(os.getenv("GEMINI_TEMPERATURE", "0.6"))
RETRY_MAX_MKT   = int(os.getenv("GEMINI_RETRY_MAX", "5"))

# Clamp output tokens an toàn (đa số model text hiện ~<= 8192 output tokens)
SAFE_HARD_CEILING = int(os.getenv("GEMINI_SAFE_HARD_CEILING", "8192"))
# ✅ Sửa default về 4096 thay vì 6096
MAX_TOKENS_ENV    = int(os.getenv("GEMINI_MAX_OUTPUT", "6300"))
MAX_TOKENS_MKT    = max(256, min(MAX_TOKENS_ENV, SAFE_HARD_CEILING))

# (Tuỳ chọn) MIME type mặc định cho text
RESPONSE_MIME_TYPE_MKT = os.getenv("GEMINI_RESPONSE_MIME", "text/markdown")

# =========================
# IMAGE (New SDK) — FREE
# =========================
CLIENT_MKT = genai_new.Client(api_key=API_KEY_MKT_FB)

if FREE_ONLY:
    GEMINI_IMAGE_MODEL_MKT = os.getenv(
        "GEMINI_IMAGE_MODEL",
        "gemini-2.0-flash-preview-image-generation"  # FREE
    )
    IMAGEN_MODEL_MKT = None  # tắt Imagen (trả phí) khi FREE_ONLY=1
else:
    GEMINI_IMAGE_MODEL_MKT = os.getenv(
        "GEMINI_IMAGE_MODEL",
        "gemini-2.5-flash-image-preview"             # PAID
    )
    IMAGEN_MODEL_MKT = os.getenv(
        "IMAGEN_MODEL",
        "imagen-4.0-generate-preview-06-06"          # PAID
    )

# =========================
# Helpers
# =========================
def tokens_for_words(words: int) -> int:
    """Ước lượng tokens ≈ 1.6 * số từ (biên rộng)."""
    return max(256, int(words * 1.6))

def _exponential_backoff_sleep(i: int, base: float = 0.6) -> None:
    time.sleep(base * (2 ** i) + random.uniform(0, 0.4))

def call_text(prompt: str,
              *,
              max_output_tokens: int | None = None,
              temperature: float | None = None,
              system_instruction: str | None = None) -> str:
    """Gọi text (free). Có retry/backoff khi gặp 429, tự hạ token nếu vượt trần."""
    want_tokens = max_output_tokens or MAX_TOKENS_MKT
    want_tokens = max(256, min(int(want_tokens), SAFE_HARD_CEILING))
    temp = TEMPERATURE_MKT if temperature is None else float(temperature)

    model = genai_old.GenerativeModel(
        model_name=TEXT_MODEL_MKT_FB,
        system_instruction=(system_instruction or None),
    )

    for i in range(RETRY_MAX_MKT):
        try:
            r = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": want_tokens,
                    "temperature": temp,
                    "candidate_count": 1,
                    "response_mime_type": RESPONSE_MIME_TYPE_MKT,
                },
            )
            return getattr(r, "text", "") or ""
        except Exception as e:
            msg = str(e).lower()
            # Quota/Rate limit
            if "429" in msg or "quota" in msg or "rate limit" in msg:
                _exponential_backoff_sleep(i)
                continue
            # Vượt trần output tokens
            if "max_output_tokens" in msg or "exceed" in msg or "too many" in msg:
                want_tokens = max(1024, want_tokens // 2)
                continue
            raise
    raise RuntimeError("Retry limit reached. Hãy giảm tốc độ hoặc tăng quota.")

def call_image(prompt: str):
    """Gọi image (free). Trả về đối tượng phản hồi của SDK mới (tuỳ bạn trích xuất)."""
    return CLIENT_MKT.models.generate_content(
        model=GEMINI_IMAGE_MODEL_MKT,
        contents=[prompt],
    )
