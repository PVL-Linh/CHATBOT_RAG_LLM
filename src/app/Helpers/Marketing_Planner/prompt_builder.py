from typing import Dict
from .prompt_planner import (
    Prompt_Blog_Website_Planner,         # hoặc V2 nếu bạn đã có
    Prompt_FaceBook_Planner,
    Prompt_Instagram_Planner,
    Prompt_LinkedIn_Planner,
    Prompt_TikTok_Planner,
    Prompt_YouTube_Planner,
    Prompt_Zalo_OA_Planner,
)
import re
from typing import Dict
STRUCTURE_TEMPLATES: Dict[str, str] = {
    "blog_longform": Prompt_Blog_Website_Planner,
    "facebook_post": Prompt_FaceBook_Planner,
    "instagram_post": Prompt_Instagram_Planner,
    "linkedin_post": Prompt_LinkedIn_Planner,
    "tiktok_script": Prompt_TikTok_Planner,
    "youtube_script": Prompt_YouTube_Planner,
    "zalo_oa_post": Prompt_Zalo_OA_Planner,
}

SYSTEM_SCAFFOLD = """
    Bạn là chiến lược gia nội dung của Tiximax Logistics.
    Ngôn ngữ đầu ra: {lang}.
    Giọng điệu ưu tiên: {tones}.

    Nguyên tắc:
    - Không bịa đặt giá, khuyến mãi, hay dữ liệu.
    - Bám sát mục tiêu truyền thông và giai đoạn hành trình khách hàng.
    - Tuân thủ ràng buộc của kênh và cấu trúc đầu ra.

    ĐẶC TẢ KÊNH:
    - Tên kênh: {name}
    - Nền tảng: {platform}
    - Đối tượng: {audience}
    - Tone: {tone}
    - Guidelines nội dung: {content_guide}
    - Phong cách hình ảnh: {visual_guide}
    - Định dạng ưa thích: {formats}
    - Giới hạn độ dài: {length}
    - Hashtags: {hashtags}
    - CTA: {cta}
    - Rủi ro/Ghi chú: {risk_notes}
    - Hướng dẫn đặc biệt: {special}

    ĐẦU RA (markdown) — theo preset: {structure_title}
    {structure_block}

    (Chỉ trả về đúng output yêu cầu. Không kèm bình luận ngoài lề.)
    """.strip()

def build_system_prompt_dynamic(ch: Dict, lang: str, tones_line: str, include_toc: bool = False) -> str:
    if (ch.get("system_prompt_override") or "").strip():
        prompt = ch["system_prompt_override"].strip()
        return _strip_toc_from_template(prompt) if not include_toc else prompt

    structure = (ch.get("structure") or "blog_longform").strip().lower()
    structure_block = STRUCTURE_TEMPLATES.get(structure, Prompt_Blog_Website_Planner).strip()

    if not include_toc:
        structure_block = _strip_toc_from_template(structure_block)
        extra_rule = "\n- KHÔNG tạo Mục lục (TOC).\n"
    else:
        extra_rule = ""

    return SYSTEM_SCAFFOLD.format(
        lang=lang,
        tones=tones_line or "Chuyên nghiệp, rõ ràng",
        name=ch.get("name",""),
        platform=ch.get("platform",""),
        audience=ch.get("audience",""),
        tone=ch.get("tone",""),
        content_guide=ch.get("content_guide",""),
        visual_guide=ch.get("visual_guide",""),
        formats=ch.get("formats",""),
        length=ch.get("length",""),
        hashtags=ch.get("hashtags",""),
        cta=ch.get("cta",""),
        risk_notes=ch.get("risk_notes",""),
        special=ch.get("special",""),
        structure_title=structure,
        structure_block=(structure_block + extra_rule),
    )



def _strip_toc_from_template(md: str) -> str:
    # 1) Xóa dòng bullet “- Mục lục (TOC)” trong phần “Cấu trúc & Đầu ra”
    md = re.sub(r"(?im)^\s*-\s*Mục lục\s*\(TOC\)\s*$", "", md)

    # 2) Nếu template nào có heading “Mục lục” thực sự, cắt nguyên block đó
    # (từ dòng “Mục lục” tới trước H1/H2/H3 tiếp theo)
    md = re.sub(
        r"(?is)^\s*(?:#+\s*Mục\s*lục|Mục\s*lục)\s*\n.*?(?=\n#{1,3}\s|\Z)",
        "",
        md,
        flags=re.MULTILINE
    )
    return md.strip()


