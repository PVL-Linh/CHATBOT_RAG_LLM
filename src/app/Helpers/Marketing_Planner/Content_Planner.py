from .prompt_planner import (Prompt_Blog_Website_Planner, 
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
        You are the content strategist for Tiximax Logistics.
        Output language: {lang}.
        Preferred tone: {tones_line}.

        Principles:

        Do not fabricate any data, prices, or promotions.

        Stay aligned with the objective and the customer journey stage.

        Follow the structure required by the channel.
        """.strip()

    if channel == "Facebook Fanpage Chính Thức":
        ch_block = Prompt_FaceBook_Planner.strip()
    elif channel == "TikTok Short Video":
        ch_block = Prompt_TikTok_Planner.strip()
    elif channel == "Instagram Reels":
        ch_block = Prompt_Instagram_Planner.strip()
    elif channel == "Blog Website SEO":
        ch_block = Prompt_Blog_Website_Planner.strip()
    elif channel == "Zalo Official Account":
        ch_block = Prompt_Zalo_OA_Planner.strip()
    elif channel == "YouTube Shorts":
        ch_block = Prompt_YouTube_Planner.strip()
    elif channel == "LinkedIn Business":
        ch_block = Prompt_LinkedIn_Planner.strip()
    # else:
    #     ch_block = f"""
    #     ĐẦU RA (markdown):

    #     Tiêu đề/Hook

    #     Mục tiêu: …
    #     Giai đoạn: … Kênh: {channel or "Không chỉ định"} Định dạng: … Độ dài: …
    #     Giọng điệu: … Từ khoá chiến lược: …

    #     Dàn ý nội dung

    #     3–6 bullet phù hợp kênh

    #     Viết phần nội dung mẫu ngắn gọn theo kênh/định dạng được chọn""".strip()
    return base + "\n\n" + ch_block

def build_user_prompt_body(d: dict) -> str:
    goal     = d.get("goal") or (d.get("objectives") or [None])[0]
    stage    = d.get("stage", "")
    channel  = (d.get("channel") or "").strip()
    format   = d.get("format", "")
    length   = d.get("length", "")
    tones    = d.get("tones", [])
    keywords = d.get("keywords", "")
    offer    = d.get("offer", "")
    cta      = d.get("cta", "")
    lang     = d.get("lang", "Tiếng Việt")
    include_toc = bool(d.get("include_toc", False))

    meta_title = d.get("meta_title", "").strip()
    meta_desc  = d.get("meta_description", "").strip()
    slug       = d.get("slug", "").strip()

    tone_line = ", ".join(tones) if tones else "Trung tính/chuyên nghiệp"

    fixed_meta_lines = []
    if meta_title:
        fixed_meta_lines.append(f"- Meta Title (dùng đúng, không tự tạo lại): {meta_title}")
    if meta_desc:
        fixed_meta_lines.append(f"- Meta Description (dùng đúng, không tự tạo lại): {meta_desc}")
    if slug:
        fixed_meta_lines.append(f"- URL Slug (dùng đúng, không tự tạo lại): {slug}")
    if not include_toc:
        fixed_meta_lines.append("- KHÔNG tạo Mục lục (TOC) trong đầu ra.")

    fixed_meta_txt = "\n".join(fixed_meta_lines) if fixed_meta_lines else "- (Không có meta cố định)"

    return f"""
        Language: {lang}
        Primary communication objective: {goal or "Not specified"}
        Customer journey stage: {stage or "Not specified"}
        Channel: {channel or "Not specified"}
        Format: {format or "Not specified"}
        Content length: {length or "Not specified"}
        Tone: {tone_line}
        Strategic keywords: {keywords or "None"}
        Promotion (if any): {offer or "None"}
        Call-to-Action: {cta or "None"}

        Ràng buộc đầu ra thêm:
        {fixed_meta_txt}

        Hãy xuất đúng **cấu trúc** đã được định nghĩa trong SYSTEM PROMPT (markdown). 
        Nếu có meta ở trên thì **dùng nguyên văn**, **không** tự tạo lại. 
        """.strip()


# --- Helpers: mô tả kênh cho Gemini / built-in spec ---
def _describe_custom_channel(ch: dict, lang: str) -> str:
    return f"""
    Channel name: {ch.get('name','')}
    Platform: {ch.get('platform','')}
    Audience: {ch.get('audience','')}
    Tone: {ch.get('tone','')}
    Content guidelines: {ch.get('content_guide','')}  # <-- NEW
    Visual style: {ch.get('visual_guide','')}
    Preferred formats: {ch.get('formats','')}
    Length limits: {ch.get('length','')}
    Hashtags: {ch.get('hashtags','')}
    Call-to-Action: {ch.get('cta','')}
    Risks/Notes: {ch.get('risk_notes','')}
    Special instructions: {ch.get('special','')}
    Output language: {lang}

    """.strip()

def _describe_builtin_channel(channel: str, lang: str) -> str:
    mapping = {
        "Facebook": Prompt_FaceBook_Planner,
        "TikTok": Prompt_TikTok_Planner,
        "Instagram": Prompt_Instagram_Planner,
        "Blog Website": Prompt_Blog_Website_Planner,
        "Zalo OA": Prompt_Zalo_OA_Planner,
        "YouTube": Prompt_YouTube_Planner,
        "LinkedIn": Prompt_LinkedIn_Planner,
    }
    base = mapping.get(channel, "Generic channel")
    return f"Kênh: {channel}\nNgôn ngữ đầu ra: {lang}\nThông số:\n{base}"
