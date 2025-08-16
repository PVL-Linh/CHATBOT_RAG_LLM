from .promt_planner import (Prompt_Blog_Website_Planner, 
                            Prompt_FaceBook_Planner, 
                            Prompt_Instagram_Planner, 
                            Prompt_LinkedIn_Planner, 
                            Prompt_TikTok_Planner, 
                            Prompt_YouTube_Planner, 
                            Prompt_Zalo_OA_Planner)
# ========= Helpers chọn prompt theo kênh (if/elif) =========

def _normalize_channel(s: str) -> str:
    s = (s or "").strip().lower()
    if s in ("fb", "facebook"):   return "Facebook"
    if s in ("tt", "tiktok"):     return "TikTok"
    if s in ("ig", "instagram"):  return "Instagram"
    if s in ("blog", "blog website", "website"): return "Blog Website"
    if s in ("zalo", "zalo oa"):  return "Zalo OA"
    if s in ("yt", "youtube"):    return "YouTube"
    if s in ("linkedin",):        return "LinkedIn"
    return s.title() if s else ""


def _build_system_prompt_ifelse(channel: str, goal: str, tones: list[str], lang: str) -> str:
    tones_line = ", ".join(tones) if tones else "Chuyên nghiệp, rõ ràng"
    base = f"""
        Bạn là chiến lược gia nội dung cho **Tiximax Logistics**.
        Ngôn ngữ đầu ra: {lang}.
        Giọng điệu ưu tiên: {tones_line}.
        Nguyên tắc:
        - Không bịa số liệu/giá/ưu đãi.
        - Bám mục tiêu & giai đoạn hành trình khách hàng.
        - Viết đúng cấu trúc yêu cầu của kênh.
        """.strip()

    if channel == "Facebook":
        ch_block = Prompt_FaceBook_Planner.strip()
    elif channel == "TikTok":
        ch_block = Prompt_TikTok_Planner.strip()
    elif channel == "Instagram":
        ch_block = Prompt_Instagram_Planner.strip()
    elif channel == "Blog Website":
        ch_block = Prompt_Blog_Website_Planner.strip()
    elif channel == "Zalo OA":
        ch_block = Prompt_Zalo_OA_Planner.strip()
    elif channel == "YouTube":
        ch_block = Prompt_YouTube_Planner.strip()
    elif channel == "LinkedIn":
        ch_block = Prompt_LinkedIn_Planner.strip()
    else:
        ch_block = f"""
        ĐẦU RA (markdown):

        Tiêu đề/Hook (≤12 từ)

        Mục tiêu: …
        Giai đoạn: … Kênh: {channel or "Không chỉ định"} Định dạng: … Độ dài: …
        Giọng điệu: … Từ khoá chiến lược: …

        Dàn ý nội dung

        3–6 bullet phù hợp kênh

        Bản thảo ngắn gọn

        Viết phần nội dung mẫu ngắn gọn theo kênh/định dạng được chọn""".strip()
    return base + "\n\n" + ch_block

def build_user_prompt_body(d: dict) -> str:
    goal = d.get("goal") or (d.get("objectives") or [None])[0]
    stage = d.get("stage", "")
    channel = _normalize_channel(d.get("channel", ""))
    print(f"Normalized channel: {channel}")  # Debug log
    format = d.get("format", "")
    length = d.get("length", "")
    tones = d.get("tones", [])
    keywords = d.get("keywords", "")
    offer = d.get("offer", "")
    cta = d.get("cta", "")
    lang = d.get("lang", "Tiếng Việt")
    tone_line = ", ".join(tones) if tones else "Trung tính/chuyên nghiệp"

    # >>> DÒNG BẠN YÊU CẦU: gắn đúng Kênh truyền thông: {channel or "Không chỉ định"}
    return f"""
        Ngôn ngữ: {lang}
        Mục tiêu truyền thông chính: {goal or "Không chỉ định"}
        Giai đoạn hành trình khách hàng: {stage or "Không chỉ định"}
        Kênh truyền thông: {channel or "Không chỉ định"}
        Định dạng: {format or "Không chỉ định"}
        Độ dài nội dung: {length or "Không chỉ định"}
        Giọng điệu: {tone_line}
        Từ khoá chiến lược: {keywords or "Không có"}
        Chương trình ưu đãi (nếu có): {offer or "Không có"}
        Call-to-Action: {cta or "Không có"}

        Hãy xuất đúng format trong system prompt (markdown).
        """.strip()

