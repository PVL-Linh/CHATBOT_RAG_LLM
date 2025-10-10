import os, time, random
import google.generativeai as genai_old
from google import genai as genai_new
from dotenv import load_dotenv
load_dotenv()

API_KEY_MKT = os.environ.get("GEMINI_API_KEY")
if not API_KEY_MKT:
    raise RuntimeError("Không tìm thấy GEMINI_API_KEY trong .env")

# =========================
# Free-only switch
# =========================
FREE_ONLY = os.environ.get("GEMINI_FREE_ONLY", "1") == "1"  # 1 = chỉ dùng model free

# =========================
# TEXT (Old SDK) — FREE
# =========================
genai_old.configure(api_key=API_KEY_MKT)

TEXT_MODEL_MKT  = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")  # FREE
TEMPERATURE_MKT = float(os.environ.get("GEMINI_TEMPERATURE", "0.6"))
RETRY_MAX_MKT   = int(os.environ.get("GEMINI_RETRY_MAX", "5"))

# Clamp output tokens an toàn (đa số model text hiện ~<= 8192 output tokens)
SAFE_HARD_CEILING = int(os.environ.get("GEMINI_SAFE_HARD_CEILING", "8192"))
# ✅ Sửa default về 4096 thay vì 6096
MAX_TOKENS_ENV    = int(os.environ.get("GEMINI_MAX_OUTPUT", "6300"))
MAX_TOKENS_MKT    = max(256, min(MAX_TOKENS_ENV, SAFE_HARD_CEILING))

# (Tuỳ chọn) MIME type mặc định cho text
RESPONSE_MIME_TYPE_MKT = os.environ.get("GEMINI_RESPONSE_MIME", "text/markdown")

# =========================
# IMAGE (New SDK) — FREE
# =========================
CLIENT_MKT = genai_new.Client(api_key=API_KEY_MKT)

if FREE_ONLY:
    GEMINI_IMAGE_MODEL_MKT = os.environ.get(
        "GEMINI_IMAGE_MODEL",
        "gemini-2.0-flash-preview-image-generation"  # FREE
    )
    IMAGEN_MODEL_MKT = None  # tắt Imagen (trả phí) khi FREE_ONLY=1
else:
    GEMINI_IMAGE_MODEL_MKT = os.environ.get(
        "GEMINI_IMAGE_MODEL",
        "gemini-2.5-flash-image-preview"             # PAID
    )
    IMAGEN_MODEL_MKT = os.environ.get(
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

# --- MIME cho Gemini text ---
ALLOWED_RESPONSE_MIMES = {
    "text/plain",
    "application/json",
    "application/xml",
    "application/yaml",
    "text/x.enum",
}

def _sanitize_mime(m: str | None) -> str | None:
    """
    Trả về MIME hợp lệ cho Gemini; nếu không hợp lệ -> 'text/plain'.
    Cho None để bỏ field khỏi generation_config.
    """
    if not m:
        return None
    m = m.strip().lower()
    return m if m in ALLOWED_RESPONSE_MIMES else "text/plain"


def call_text(prompt: str,
              *,
              max_output_tokens: int | None = None,
              temperature: float | None = None,
              system_instruction: str | None = None) -> str:
    """
    Gọi text (free) với retry/backoff + bóc text an toàn (KHÔNG dùng response.text accessor).
    - Không raise do 'no Part' khi MAX_TOKENS.
    - Trả về "" nếu thật sự không có text; tầng trên tự fallback.
    """
    want_tokens = max_output_tokens or MAX_TOKENS_MKT
    want_tokens = max(256, min(int(want_tokens), SAFE_HARD_CEILING))
    temp = TEMPERATURE_MKT if temperature is None else float(temperature)

    import os as _os
    resp_mime_env = _os.environ.get("GEMINI_RESPONSE_MIME", "text/plain")
    resp_mime = _sanitize_mime(resp_mime_env)

    model = genai_old.GenerativeModel(
        model_name=TEXT_MODEL_MKT,
        system_instruction=(system_instruction or None),
    )

    def _extract_text_safe(resp) -> str:
        # 1) Tránh dùng resp.text vì dễ ném lỗi khi không có Part
        txt = ""
        try:
            # old SDK đôi khi vẫn có resp.text; giữ nhưng bọc try
            t = getattr(resp, "text", None)
            if isinstance(t, str) and t.strip():
                return t
        except Exception as e:
            print("[call_text] resp.text accessor failed:", e)

        # 2) Bóc thủ công từ candidates -> content.parts[*].text
        try:
            cands = getattr(resp, "candidates", None) or []
            buf = []
            for c in cands:
                cont = getattr(c, "content", None)
                if not cont:
                    continue
                parts = getattr(cont, "parts", None) or []
                for p in parts:
                    # Part có thể là object có .text hoặc dict {'text':...}
                    t = getattr(p, "text", None)
                    if t:
                        buf.append(str(t))
                    elif isinstance(p, dict) and "text" in p:
                        buf.append(str(p["text"]))
            txt = "\n".join(buf).strip()
        except Exception as e:
            print("[call_text] manual extract failed:", e)
            txt = ""

        return txt or ""

    def _finish_name(fr_val) -> str:
        try:
            fr_map = {0: "UNSPECIFIED", 1: "STOP", 2: "MAX_TOKENS", 3: "SAFETY", 4: "OTHER"}
            return fr_map.get(int(fr_val), str(fr_val))
        except Exception:
            return str(fr_val)

    for i in range(RETRY_MAX_MKT):
        try:
            r = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": want_tokens,
                    "temperature": temp,
                    "candidate_count": 1,
                    **({"response_mime_type": resp_mime} if resp_mime else {}),
                },
                request_options={"timeout": 180},
            )

            # Log finish + usage (best-effort)
            try:
                fr = r.candidates[0].finish_reason if getattr(r, "candidates", None) else "UNKNOWN"
                usage = getattr(r, "usage_metadata", None)
                print("FINISH:", _finish_name(fr), "| TOKENS:", getattr(usage, "total_token_count", "?"))
            except Exception:
                pass

            # LẤY TEXT AN TOÀN
            out_text = _extract_text_safe(r)

            # Nếu rỗng và lỗi là MAX_TOKENS, giảm ngân sách rồi thử lại 1–2 lần
            try:
                fr_val = r.candidates[0].finish_reason if getattr(r, "candidates", None) else None
            except Exception:
                fr_val = None

            if (not out_text) and (fr_val == 2):  # MAX_TOKENS, không có Part/text
                want_tokens = max(512, int(want_tokens * 0.85))  # hạ 15%
                _exponential_backoff_sleep(i)
                continue

            return out_text  # có thể là "" -> tầng trên sẽ tự fallback

        except Exception as e:
            msg = str(e).lower()

            if "response_mime_type" in msg or "allowed mimetypes" in msg:
                print("WARN: Invalid response_mime_type, falling back to None")
                resp_mime = None
                _exponential_backoff_sleep(i)
                continue

            if "429" in msg or "quota" in msg or "rate limit" in msg:
                print("QUOTA/RATE:", e)
                _exponential_backoff_sleep(i)
                continue

            if "max_output_tokens" in msg or "exceed" in msg or "too many" in msg:
                want_tokens = max(512, int(want_tokens * 0.85))
                print("LOWER max_output_tokens ->", want_tokens)
                _exponential_backoff_sleep(i)
                continue

            if "deadline exceeded" in msg or "timeout" in msg:
                print("TIMEOUT:", e)
                _exponential_backoff_sleep(i)
                continue

            # Lỗi khác -> ghi log nhưng trả "" để tầng trên fallback (không raise)
            print("[call_text] unexpected error:", e)
            return ""

    # Quá số lần thử -> trả "" (không raise)
    return ""
