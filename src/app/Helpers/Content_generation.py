from langchain_core.messages import SystemMessage
from .LLM_client import call_gemini_flash, apply_occasion_lock
from .prompt_KT import persona_vi
from .prompts_extra import prompt_rephrase_vi, prompt_fab_vi, prompt_tiktok_vi
def generate_facebook_ads_content(
    product_desc: str, 
    customer: str, 
    lang: str = "Tiếng Việt"
) -> str:
    """Generate Facebook Ads content using Gemini Flash"""
    user_prompt = f"""
Tạo nội dung truyền thông theo mẫu cố định bên dưới cho chiến dịch Facebook Ads.
Ngôn ngữ: {lang}.
Thông tin đầu vào:
- Mô tả sản phẩm: {product_desc}
- Chân dung khách hàng: {customer}
Chỉ xuất MỘT bài hoàn chỉnh đúng template (Phân tích → Ý tưởng chiến dịch → Kịch bản video → Bài viết cho Facebook → IMAGE_PROMPT).
"""
    
    user_prompt, system_instruction = apply_occasion_lock(user_prompt, persona_vi)
    return call_gemini_flash(user_prompt, system_instruction, [SystemMessage(persona_vi)])

def generate_rephrase_content(
    text_src: str, 
    lang: str = "Tiếng Việt", 
    tone: str = "Chuyên nghiệp"
) -> str:
    """Generate rephrased content using Gemini Flash"""
    system_prompt = prompt_rephrase_vi.strip()
    
    user_prompt = f"""
Ngôn ngữ: {lang}
Giọng điệu: {tone}
Văn bản gốc: ```{text_src.strip()}```
Hãy xuất đúng định dạng theo system prompt.
"""
    
    return call_gemini_flash(user_prompt, system_prompt, [])

def generate_tiktok_content(
    brief: str, 
    lang: str = "Tiếng Việt", 
    duration: int = 20, 
    objective: str = "Chuyển đổi inbox"
) -> str:
    """Generate TikTok content ideas using Gemini Flash"""
    system_prompt = prompt_tiktok_vi.strip()
    
    user_prompt = f"""
Ngôn ngữ: {lang}
Thời lượng: {duration}s
Mục tiêu: {objective}
Tóm tắt: {brief}
Hãy xuất đúng cấu trúc IDEAS theo system prompt (không hướng dẫn quay).
"""
    
    return call_gemini_flash(user_prompt, system_prompt, [])

def generate_fab_content(
    benefits: str, 
    lang: str = "Tiếng Việt", 
    extra: str = ""
) -> str:
    """Generate FAB (Features-Advantages-Benefits) content using Gemini Flash"""
    system_prompt = prompt_fab_vi.strip()
    
    user_prompt = f"""
Ngôn ngữ: {lang}
Lợi ích: {benefits}
Thông tin bổ sung: {extra or 'Không có'}
Xuất đúng khung FAB theo system prompt.
"""
    
    return call_gemini_flash(user_prompt, system_prompt, [])