import os
from typing import Optional

def init_gemini():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key or "your_real_key_here" in (api_key or "").lower():
        raise RuntimeError(
            "Chưa thấy GEMINI_API_KEY (hoặc GOOGLE_API_KEY). Thêm vào .env: GEMINI_API_KEY=xxxxxxx"
        )
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)
        return genai
    except Exception as e:
        raise RuntimeError(
            f"Lỗi khởi tạo Gemini. Đảm bảo đã cài 'google-generativeai'. Chi tiết: {e}"
        )

def ask_gemini(genai, model_name: str, sys_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    generation_config = {"response_mime_type": "application/json"} if json_mode else None
    model = genai.GenerativeModel(model_name, system_instruction=sys_prompt)
    resp = model.generate_content(user_prompt, generation_config=generation_config)
    return (resp.text or "").strip()
