
import os, re, time, threading
from typing import List, Optional, Tuple

import google.generativeai as genai_old
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from .prompt_KT import persona_vi  # nếu cần
from .Occasion_Classifier import classify_occasion_1
from .config_MKT import TEXT_MODEL_MKT, TEMPERATURE_MKT, MAX_TOKENS_MKT, RETRY_MAX_MKT
from .rate_limit import get_text_limiter

# ===================== Semaphore (đồng thời cho LLM)
LLM_SEM = threading.Semaphore(int(os.getenv("SEM_LLM", "24")))

# ===================== Helpers
def to_gemini_history(msgs: List[object]) -> List[dict]:
    out = []
    for m in msgs or []:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "parts": [m.content]})
        elif isinstance(m, AIMessage):
            out.append({"role": "model", "parts": [m.content]})
    return out

def _estimate_tokens(prompt: str, out_tokens: int) -> int:
    return int(1.3 * max(1, len((prompt or "").split()))) + int(out_tokens or 512)

# ===================== LLM (TEXT)
def call_gemini_flash(user_prompt: str, system_instruction: str, history_msgs: List[object] = None) -> str:
    """
    Gọi Gemini Flash có: limiter (RPM/TPM) + semaphore + retry/backoff.
    API giữ nguyên chữ ký để các route cũ dùng được.
    """
    if history_msgs is None:
        history_msgs = []

    gen_cfg = {"temperature": TEMPERATURE_MKT, "max_output_tokens": MAX_TOKENS_MKT}
    model = genai_old.GenerativeModel(model_name=TEXT_MODEL_MKT, system_instruction=system_instruction)
    chat = model.start_chat(history=to_gemini_history(history_msgs))

    limiter = get_text_limiter()
    tokens_est = _estimate_tokens(user_prompt, MAX_TOKENS_MKT)
    back = 0.4
    last_err = None

    for _ in range(RETRY_MAX_MKT):
        try:
            limiter.acquire(tokens_est)
            with LLM_SEM:
                resp = chat.send_message(user_prompt, generation_config=gen_cfg)
            limiter.on_success()
            return (resp.text or "").strip()
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if ("429" in msg or "quota" in msg or "rate" in msg) and back <= 10:
                limiter.on_429()
                time.sleep(back)
                back *= 2
                continue
            limiter.on_429()
            break
    raise RuntimeError(f"Quá số lần retry khi gọi Gemini. Chi tiết: {last_err}")

# ===================== Prompt utils
def ensure_english_prompt(text: str) -> str:
    """Dịch/chỉnh prompt ảnh sang English (dùng limiter + semaphore)."""
    try:
        limiter = get_text_limiter()
        tokens_est = _estimate_tokens(text, 150)
        limiter.acquire(tokens_est)
        with LLM_SEM:
            model = genai_old.GenerativeModel(
                model_name=TEXT_MODEL_MKT,
                system_instruction=(
                    "You are a precise translator/editor for text-to-image prompts. "
                    "Rewrite concisely for SD/MJ/Imagen/Gemini image; keep proper nouns; "
                    "no extra details; output only the final prompt text."
                )
            )
            resp = model.generate_content(text, generation_config={"temperature": 0.2, "max_output_tokens": 150})
        limiter.on_success()
        return (resp.text or "").strip() or text
    except Exception:
        return text

def extract_image_prompt(text: str) -> Optional[str]:
    patterns = [
        r"```(?:image_prompt|txt2img|image|prompt_anh)\s*\n(.+?)```",
        r"(?:IMAGE[_\s]*PROMPT|PROMPT[_\s]*IMAGE|PROMPT[_\s]*ẢNH|PROMPT[_\s]*ANH)\s*:\s*(.+)$"
    ]
    for pattern in patterns:
        m = re.search(pattern, text or "", re.S | re.I)
        if m:
            return m.group(1).strip()
    return None

def apply_occasion_lock(user_prompt: str, system_instruction: str) -> Tuple[str, str]:
    """Chèn constraint theo dịp (không dựng lại prompt từ đầu)."""
    try:
        occasion = classify_occasion_1(user_prompt)
    except NameError:
        occasion = classify_occasion_1(user_prompt)

    if occasion == "national_day":
        system_instruction += (
            "\n\n### Occasion Lock (MANDATORY)\n"
            "- Theme: Vietnam National Day (2/9).\n"
            "- Do NOT mention Lunar New Year/Tết.\n"
            "- Use VN flags, fireworks over HCMC, red–gold palette.\n"
        )
        user_prompt = (
            "IMPORTANT: This request is for Vietnam National Day (2/9). "
            "Do not interpret as Lunar New Year.\n\n" + user_prompt
        )

    return user_prompt, system_instruction

