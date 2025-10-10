# -*- coding: utf-8 -*-
"""
Config dành riêng cho flow 'Image-First' (mượn cùng API key/model với FB contents).
Tách file để dễ quản lý và điều chỉnh độc lập nếu cần.
"""
import os, time, random
import google.generativeai as genai_old
from google import genai as genai_new
from app.config.utils_env import load_env_near
load_env_near(__file__)

API_KEY_MKT_FB = os.getenv("GEMINI_API_KEY_IMGFB") or os.getenv("GEMINI_API_KEY_FB")
if not API_KEY_MKT_FB:
    raise RuntimeError("Không tìm thấy GEMINI_API_KEY_FB / GEMINI_API_KEY trong .env")

FREE_ONLY = os.getenv("GEMINI_FREE_ONLY", "1") == "1"

# Text (old SDK)
genai_old.configure(api_key=API_KEY_MKT_FB)
TEXT_MODEL_IMG_FIRST = os.getenv("GEMINI_TEXT_MODEL_FB", "gemini-2.5-flash")
TEMPERATURE_IMG_FIRST = float(os.getenv("GEMINI_TEMPERATURE", "0.6"))
SAFE_HARD_CEILING = int(os.getenv("GEMINI_SAFE_HARD_CEILING", "8192"))
MAX_TOKENS_IMG_FIRST = max(256, min(int(os.getenv("GEMINI_MAX_OUTPUT", "4096")), SAFE_HARD_CEILING))
RESPONSE_MIME_TYPE = os.getenv("GEMINI_RESPONSE_MIME", "text/markdown")
RETRY_MAX = int(os.getenv("GEMINI_RETRY_MAX", "5"))

# Image (new SDK)
CLIENT_IMG_FIRST = genai_new.Client(api_key=API_KEY_MKT_FB)
if FREE_ONLY:
    GEMINI_IMAGE_MODEL_IMG_FIRST = os.getenv(
        "GEMINI_IMAGE_MODEL",
        "gemini-2.0-flash-preview-image-generation"  # FREE
    )
    IMAGEN_MODEL_IMG_FIRST = None
else:
    GEMINI_IMAGE_MODEL_IMG_FIRST = os.getenv(
        "GEMINI_IMAGE_MODEL",
        "gemini-2.5-flash-image-preview"             # PAID
    )
    IMAGEN_MODEL_IMG_FIRST = os.getenv("IMAGEN_MODEL", "imagen-4.0-generate-preview-06-06")

def _backoff(i: int, base: float = 0.6):
    time.sleep(base * (2 ** i) + random.uniform(0, 0.4))

def call_text_imgfirst(prompt: str,
                       max_output_tokens: int | None = None,
                       temperature: float | None = None,
                       system_instruction: str | None = None) -> str:
    want = max_output_tokens or MAX_TOKENS_IMG_FIRST
    want = max(256, min(int(want), SAFE_HARD_CEILING))
    temp = TEMPERATURE_IMG_FIRST if temperature is None else float(temperature)
    model = genai_old.GenerativeModel(
        model_name=TEXT_MODEL_IMG_FIRST,
        system_instruction=(system_instruction or None),
    )
    for i in range(RETRY_MAX):
        try:
            r = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": want,
                    "temperature": temp,
                    "candidate_count": 1,
                    "response_mime_type": RESPONSE_MIME_MIME if (RESPONSE_MIME_MIME := RESPONSE_MIME_TYPE) else "text/markdown",
                },
            )
            return getattr(r, "text", "") or ""
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg or "rate limit" in msg:
                _backoff(i)
                continue
            if "max_output_tokens" in msg or "exceed" in msg or "too many" in msg:
                want = max(1024, want // 2)
                continue
            raise
    raise RuntimeError("Retry limit reached (Image-First).")
