# Marketing_Planner/Content_Planner.py
from .prompt_planner import (
                            Prompt_Blog_Website_Planner,
                            Prompt_FaceBook_Planner,
                            Prompt_Instagram_Planner,
                            Prompt_LinkedIn_Planner,
                            Prompt_TikTok_Planner,
                            Prompt_YouTube_Planner,
                            Prompt_Zalo_OA_Planner,
                        )

from .repeat_guard import jaccard_sentence_overlap
from app.config.config_MKT import call_text
import re
from typing import List
import os
from app.config.paths import PLANNER_SHORT_CAP

def _normalize_channel(s: str) -> str:
    s = (s or "").strip().lower()
    if s in ("fb", "facebook"): return "Facebook Fanpage Chính Thức"
    if s in ("tt", "tiktok"): return "TikTok Short Video"
    if s in ("ig", "instagram"): return "Instagram Reels"
    if s in ("blog", "blog website", "website"): return "Blog Website SEO"
    if s in ("zalo", "zalo oa"): return "Zalo Official Account"
    if s in ("yt", "youtube"): return "YouTube Shorts"
    if s in ("linkedin",): return "LinkedIn Business"
    return s.title() if s else ""

def _build_system_prompt_ifelse(channel: str, goal: str, tones: list[str], lang: str, target_words: int) -> str:
    tones_line = ", ".join(tones) if tones else "Chuyên nghiệp, rõ ràng"
    base = f"""
        Bạn là chiến lược gia nội dung của Tiximax Logistics.
        Ngôn ngữ đầu ra: {lang}.
        Giọng điệu ưu tiên: {tones_line}.

        Nguyên tắc:
        - Bám sát 100% bài viết input hoặc goal/keywords/offer/cta. Không thêm ý mới ngoài input.
        - Không bịa giá, khuyến mãi, hay dữ liệu.
        - Tuân thủ cấu trúc kênh và độ dài yêu cầu ({target_words} từ ±6%).
        - Nếu target_words < 500, tóm tắt ngắn gọn ý chính từ input.
        - Nếu target_words > 1000, mở rộng chi tiết (ví dụ, phân tích, case study Tiximax).
        - Trả về Markdown sạch, không kèm bình luận ngoài lề.
        - Chỉ generate một lần, đạt đúng độ dài.
    """.strip()

    channel_mapping = {
        "Facebook Fanpage Chính Thức": (Prompt_FaceBook_Planner, "200-500 từ"),
        "TikTok Short Video": (Prompt_TikTok_Planner, "Ngắn gọn, tối đa 200 từ"),
        "Instagram Reels": (Prompt_Instagram_Planner, "Caption dưới 100 từ"),
        "Blog Website SEO": (Prompt_Blog_Website_Planner, "1500-3000+ từ, SEO-focused"),
        "Zalo Official Account": (Prompt_Zalo_OA_Planner, "Dưới 200 từ, straight to the point"),
        "YouTube Shorts": (Prompt_YouTube_Planner, "Dưới 200 từ"),
        "LinkedIn Business": (Prompt_LinkedIn_Planner, "300-800 từ"),
    }

    ch_prompt, ch_length = channel_mapping.get(channel, ("Kênh mặc định", f"{target_words} từ (±6%)"))
    ch_block = ch_prompt.strip() if ch_prompt != "Kênh mặc định" else f"""
        ĐẦU RA (markdown):
        - Tiêu đề/Hook
        - Mục tiêu: {goal or "Không chỉ định"}
        - Kênh: {channel or "Không chỉ định"} Độ dài: {ch_length}
        - Giọng điệu: {tones_line}
        - Nội dung: Viết theo input, đạt đúng độ dài trong một lần generate.
    """.strip()
    return base + "\n\n" + ch_block

def _generate_outline_if_missing(up_body: str, target_words: int, lang: str, channel: str) -> List[str]:
    length_guide = {
        "TikTok Short Video": "Ngắn gọn, 3 mục, mỗi mục 1 câu",
        "Zalo Official Account": "Ngắn gọn, 3 mục, mỗi mục 1 câu",
        "Instagram Reels": "Ngắn gọn, 3 mục, mỗi mục 1 câu",
        "Blog Website SEO": "Chi tiết, 5-7 mục, mỗi mục 2-3 câu",
    }.get(channel, "3-5 mục, mỗi mục 1-2 câu")
    outline_prompt = f"""
    Tạo outline {length_guide} cho bài viết {lang} về logistics, bám sát input sau:
    {up_body[:200]}
    - Mục tiêu: Đạt {target_words} từ (±6%).
    - Không tạo Mục lục/TOC.
    - Chỉ trả về danh sách bullet.
    """
    try:
        outline_str = call_text(outline_prompt, max_output_tokens=150, system_instruction="Tạo outline ngắn gọn.")
        lines = outline_str.strip().splitlines()
        items = [re.sub(r'^\s*[\-\*\u2022\u2023\u25E6\d]+[.)]?\s*', "", ln).strip() for ln in lines if ln.strip()]
        return [item for item in items if item and not re.match(r"(?i)^mục\s*lục$", item)]
    except Exception:
        return ["Giới thiệu", "Lợi ích chính", "Kêu gọi hành động"]

def _simple_similarity(text: str, input_ref: str) -> float:
    return jaccard_sentence_overlap(text, input_ref)

def _validate_channel_length(channel: str, target_words: int) -> int:
    length_rules = {
        "TikTok Short Video": (50, 200),
        "Zalo Official Account": (50, 200),
        "Instagram Reels": (50, 100),
        "Facebook Fanpage Chính Thức": (200, 1000),
        "Blog Website SEO": (1500, 3000),
        "YouTube Shorts": (50, 200),
        "LinkedIn Business": (300, 1000),
    }
    min_len, max_len = length_rules.get(channel, (50, 3000))
    return min(max(target_words, min_len), max_len)

def build_user_prompt_body(d: dict) -> str:
    goal = d.get("goal") or (d.get("objectives") or [None])[0]
    stage = d.get("stage", "")
    channel = _normalize_channel(d.get("channel", ""))
    format = d.get("format", "")
    tones = d.get("tones", [])
    keywords = d.get("keywords", "")
    offer = d.get("offer", "")
    cta = d.get("cta", "")
    lang = d.get("lang", "Tiếng Việt")
    target_words = _validate_channel_length(channel, int(d.get("target_words", 150)))
    full_input_content = d.get("full_content", "").strip()

    tone_line = ", ".join(tones) if tones else "Trung tính/chuyên nghiệp"

    fixed_meta_lines = []
    if d.get("meta_title", ""):
        fixed_meta_lines.append(f"- Meta Title: {d.get('meta_title')}")
    if d.get("meta_description", ""):
        fixed_meta_lines.append(f"- Meta Description: {d.get('meta_description')}")
    if d.get("slug", ""):
        fixed_meta_lines.append(f"- URL Slug: {d.get('slug')}")
    fixed_meta_lines.append("- KHÔNG tạo Mục lục (TOC).")

    fixed_meta_txt = "\n".join(fixed_meta_lines) if fixed_meta_lines else "- (Không có meta cố định)"

    scale_rule = "- Tóm tắt ngắn gọn ý chính từ bài viết input thành ~{target_words} từ, giữ cấu trúc, từ khóa, ưu đãi, CTA." if target_words < 500 else "- Mở rộng chi tiết: thêm ví dụ, phân tích, case study Tiximax, bám sát cấu trúc input."
    content_input = full_input_content[:200] if full_input_content else f"Viết dựa trên goal: {goal}, keywords: {keywords}, offer: {offer}, cta: {cta}."

    return f"""
        Ngôn ngữ: {lang}
        Mục tiêu chính: {goal or "Không chỉ định"}
        Giai đoạn hành trình khách hàng: {stage or "Không chỉ định"}
        Kênh: {channel or "Không chỉ định"}
        Định dạng: {format or "Không chỉ định"}
        Độ dài nội dung: {target_words} từ (±6%)
        Giọng điệu: {tone_line}
        Từ khóa chiến lược: {keywords or "Không có"}
        Ưu đãi (nếu có): {offer or "Không có"}
        Kêu gọi hành động: {cta or "Không có"}

        Ràng buộc đầu ra:
        {fixed_meta_txt}
        - Bám sát 100% bài viết input sau: giữ cấu trúc, tóm tắt/mở rộng theo độ dài.
        {scale_rule}
        - Không bịa dữ liệu, giữ sát Tiximax Logistics.
        - Chỉ generate một lần, đạt đúng độ dài.

        Bài viết input cần tóm tắt/mở rộng:
        {content_input}

        Hãy xuất đúng cấu trúc markdown, đạt đúng độ dài yêu cầu.
    """.strip()

def _describe_custom_channel(ch: dict, lang: str) -> str:
    length = ch.get("length", "")
    length_guide = f"{_validate_channel_length(ch.get('name', ''), 150)} từ" if length and length.isdigit() else "Theo target_words (±6%)"
    return f"""
    Tên kênh: {ch.get('name','')}
    Nền tảng: {ch.get('platform','')}
    Đối tượng: {ch.get('audience','')}
    Giọng điệu: {ch.get('tone','')}
    Hướng dẫn nội dung: {ch.get('content_guide','Bám sát input, không sáng tạo ngoài lề')}
    Phong cách hình ảnh: {ch.get('visual_guide','')}
    Định dạng ưa thích: {ch.get('formats','')}
    Giới hạn độ dài: {length_guide}
    Hashtags: {ch.get('hashtags','')}
    Kêu gọi hành động: {ch.get('cta','')}
    Rủi ro/Ghi chú: {ch.get('risk_notes','')}
    Hướng dẫn đặc biệt: {ch.get('special','')}
    Ngôn ngữ đầu ra: {lang}
    """.strip()

def _describe_builtin_channel(channel: str, lang: str) -> str:
    mapping = {
        "Facebook Fanpage Chính Thức": Prompt_FaceBook_Planner,
        "TikTok Short Video": Prompt_TikTok_Planner,
        "Instagram Reels": Prompt_Instagram_Planner,
        "Blog Website SEO": Prompt_Blog_Website_Planner,
        "Zalo Official Account": Prompt_Zalo_OA_Planner,
        "YouTube Shorts": Prompt_YouTube_Planner,
        "LinkedIn Business": Prompt_LinkedIn_Planner,
    }
    base = mapping.get(channel, "Kênh mặc định")
    return f"Kênh: {channel}\nNgôn ngữ đầu ra: {lang}\nThông số:\n{base}\n- Bám sát input, không thêm ý ngoài mục tiêu/từ khóa/ưu đãi/CTA."