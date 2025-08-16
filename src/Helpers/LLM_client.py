import time
import re
from typing import List, Optional, Tuple
import google.generativeai as genai_old
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
# Import configurations
# from config_MKT import TEXT_MODEL, TEMPERATURE, MAX_TOKENS, RETRY_MAX
from .config_MKT import TEXT_MODEL_MKT, TEMPERATURE_MKT, MAX_TOKENS_MKT, RETRY_MAX_MKT
from .Occasion_Classifier import classify_occasion_1

def to_gemini_history(msgs: List[object]) -> List[dict]:
    """Convert LangChain messages to Gemini chat history format"""
    out = []
    for m in msgs:
        if isinstance(m, HumanMessage): 
            out.append({"role": "user", "parts": [m.content]})
        elif isinstance(m, AIMessage):  
            out.append({"role": "model", "parts": [m.content]})
    return out

def call_gemini_flash(user_prompt: str, system_instruction: str, history_msgs: List[object] = None) -> str:
    """Call Gemini Flash with retry logic"""
    if history_msgs is None:
        history_msgs = []
    
    gen_cfg = {"temperature": TEMPERATURE_MKT, "max_output_tokens": MAX_TOKENS_MKT}
    model = genai_old.GenerativeModel(model_name=TEXT_MODEL_MKT, system_instruction=system_instruction)
    chat = model.start_chat(history=to_gemini_history(history_msgs))
    
    back = 1.0
    for _ in range(RETRY_MAX_MKT):
        try:
            resp = chat.send_message(user_prompt, generation_config=gen_cfg)
            return (resp.text or "").strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower():
                time.sleep(back)
                back = min(back * 2, 10)
                continue
            raise
    raise RuntimeError("Quá số lần retry khi gọi Gemini.")

def ensure_english_prompt(text: str) -> str:
    """Ensure prompt is in English for image generation"""
    try:
        model = genai_old.GenerativeModel(
            model_name=TEXT_MODEL_MKT,
            system_instruction=(
                "You are a precise translator/editor for text-to-image prompts. "
                "Rewrite concisely for SD/MJ/Imagen; keep proper nouns; no extra details; output only text."
            )
        )
        resp = model.generate_content(text, generation_config={"temperature": 0.2, "max_output_tokens": 150})
        return (resp.text or "").strip() or text
    except Exception:
        return text

def extract_image_prompt(text: str) -> Optional[str]:
    """Extract image prompt from generated text using regex patterns"""
    # Try different patterns for image prompt extraction
    patterns = [
        r"```(?:image_prompt|txt2img|image|prompt_anh)\s*\n(.+?)```",
        r"(?:IMAGE[_\s]*PROMPT|PROMPT[_\s]*IMAGE|PROMPT[_\s]*ẢNH|PROMPT[_\s]*ANH)\s*:\s*(.+)$"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.S | re.I)
        if match:
            return match.group(1).strip()
    
    return None

# def apply_occasion_lock(user_prompt: str, system_instruction: str) -> Tuple[str, str]:
#     """Apply occasion-specific constraints to prompts"""
#     occasion = classify_occasion_1(user_prompt)
    
#     if occasion == "national_day":
#         system_instruction += (
#             "\n\n### Occasion Lock (MANDATORY)\n"
#             "- Theme: Vietnam National Day (2/9).\n"
#             "- Do NOT mention Lunar New Year/Tết.\n"
#             "- Use VN flags, fireworks over HCMC, red–gold palette.\n"
#         )
#         user_prompt = f"""
#         Tạo nội dung truyền thông theo mẫu cố định bên dưới cho chiến dịch Facebook Ads.
#         Ngôn ngữ: {lang}.
#         Thương hiệu: {brand}
#         Tone giọng/Brand voice: {tone}

#         Thông tin đầu vào:
#         - Mô tả sản phẩm: {product}
#         - Chân dung khách hàng: {customer}

#         YÊU CẦU:
#         - Phản ánh đúng giọng thương hiệu (tone) đã nêu.
#         - Không bịa khuyến mãi/giá nếu không có.
#         - Chỉ xuất MỘT bài hoàn chỉnh đúng template (Phân tích → Ý tưởng chiến dịch → Kịch bản video → Bài viết cho Facebook → IMAGE_PROMPT).
#         """.strip()
    
#     return user_prompt, system_instruction

def apply_occasion_lock(user_prompt: str, system_instruction: str) -> Tuple[str, str]:
    """Apply occasion-specific constraints to prompts (add constraints only, don't rebuild full prompt)"""
    # Dùng đúng classifier sẵn có của bạn; nếu hàm là classify_occasion_1 thì giữ nguyên tên
    try:
        occasion = classify_occasion_1(user_prompt)  # hoặc classify_occasion(...)
    except NameError:
        
        occasion = classify_occasion_1(user_prompt)

    if occasion == "national_day":
        system_instruction += (
            "\n\n### Occasion Lock (MANDATORY)\n"
            "- Theme: Vietnam National Day (2/9).\n"
            "- Do NOT mention Lunar New Year/Tết.\n"
            "- Use VN flags, fireworks over HCMC, red–gold palette.\n"
        )
        # chỉ prepend cảnh báo ngữ cảnh, KHÔNG dựng lại prompt bằng biến ngoài scope
        user_prompt = (
            "IMPORTANT: This request is for Vietnam National Day (2/9). "
            "Do not interpret as Lunar New Year.\n\n" + user_prompt
        )

    return user_prompt, system_instruction
