from __future__ import annotations
import textwrap
import time as _time
from app.Helpers.Marketing_Planner.helpers_resolve import resolve_channel
from app.Helpers.Marketing_Planner.Content_Planner import build_user_prompt_body
from app.Helpers.Marketing_Planner.bounded_writer import generate_bounded_longform
from app.Helpers.Marketing_Planner.prompt_builder import build_system_prompt_dynamic
from app.Helpers.Marketing_Planner.text_postprocess import patch_meta
try:
    from langchain_core.messages import SystemMessage
except Exception:
    SystemMessage = None

try:
    from .LLM_client import call_gemini_flash_planner, apply_occasion_lock, call_gemini_flash  # type: ignore
except Exception:
    call_gemini_flash_planner = None
    call_gemini_flash = None
    def apply_occasion_lock(user_prompt: str, system_prompt: str):
        return user_prompt, system_prompt
try:
    from .prompt_KT import persona_vi
except Exception:
    persona_vi = "Bạn là trợ lý marketing của Tiximax, viết ngắn gọn, súc tích."

try:
    from .prompts_extra import prompt_rephrase_vi, prompt_fab_vi, prompt_tiktok_vi  # type: ignore
except Exception:
    prompt_rephrase_vi = "Hãy diễn đạt lại nội dung theo giọng điệu chỉ định, giữ nguyên ý chính."
    prompt_fab_vi = "Xuất nội dung theo khung FAB (Features-Advantages-Benefits)."
    prompt_tiktok_vi = "Sinh ý tưởng TikTok ngắn gọn, bám mục tiêu."

__all__ = [
    "generate_facebook_ads_content",
    "generate_rephrase_content",
    "generate_tiktok_content",
    "generate_fab_content",
    "generate_caption",
    "generate_caption_from_image_and_inputs",
]

def generate_facebook_ads_content(
    product_desc: str,
    customer: str,
    lang: str = "Tiếng Việt",
    ) -> str:
    if call_gemini_flash is not None and SystemMessage is not None:
        user_prompt = f"""
        Create marketing content following the fixed template below for a Facebook contents campaign.
        Language: {lang}.
        Input information:
        - Product description: {product_desc}
        - Customer persona: {customer}
        """
        user_prompt, system_instruction = apply_occasion_lock(user_prompt, persona_vi)
        try:
            return call_gemini_flash(user_prompt, system_instruction, [SystemMessage(persona_vi)])
        except Exception:
            pass

    return generate_caption(
        product_desc=product_desc,
        customer=customer,
        brand="Tiximax Logistics",
        lang=lang,
        tone="Chuyên nghiệp",
    )

def generate_rephrase_content(
    text_src: str,
    lang: str = "Tiếng Việt",
    tone: str = "Chuyên nghiệp",
) -> str:
    """Generate rephrased content using Gemini Flash (nếu có); nếu không có thì trả về hướng dẫn cơ bản."""
    system_prompt = (prompt_rephrase_vi or "").strip()
    user_prompt = f"""
    Ngôn ngữ: {lang}
    Giọng điệu: {tone}
    Văn bản gốc: ```{(text_src or '').strip()}```
    Hãy xuất đúng định dạng theo system prompt.
    **Mỗi câu là 1 dòng** (ONE SENTENCE PER LINE).
    """
    if call_gemini_flash_planner is not None:
        try:
            return call_gemini_flash_planner(user_prompt, system_prompt, [])
        except Exception:
            pass
    return f"[Rephrase/{lang}/{tone}] {text_src}".strip()

def generate_tiktok_content(
    brief: str,
    lang: str = "Tiếng Việt",
    duration: int = 20,
    objective: str = "Chuyển đổi inbox",
) -> str:
    """Generate TikTok content ideas using Gemini Flash (nếu có)."""
    system_prompt = (prompt_tiktok_vi or "").strip()
    user_prompt = f"""
    Ngôn ngữ: {lang}
    Thời lượng: {duration}s
    Mục tiêu: {objective}
    Tóm tắt: {brief}
    Hãy xuất đúng cấu trúc IDEAS theo system prompt (không hướng dẫn quay).
    """
    if call_gemini_flash_planner is not None:
        try:
            return call_gemini_flash_planner(user_prompt, system_prompt, [])
        except Exception:
            pass
    return textwrap.dedent(f"""
    **TikTok Ideas ({lang}, ~{duration}s, mục tiêu: {objective})**
    1) Hook mạnh + 1 lợi ích chính
    2) Điểm nổi bật sản phẩm/dịch vụ
    3) CTA: Nhắn tin ngay để được tư vấn!
    """).strip()

def generate_fab_content(
    benefits: str,
    lang: str = "Tiếng Việt",
    extra: str = "",
) -> str:
    """Generate FAB (Features-Advantages-Benefits) using Gemini Flash (nếu có)."""
    system_prompt = (prompt_fab_vi or "").strip()
    user_prompt = f"""
    Ngôn ngữ: {lang}
    Lợi ích: {benefits}
    Thông tin bổ sung: {extra or 'Không có'}
    Xuất đúng khung FAB theo system prompt.
    """
    if call_gemini_flash_planner is not None:
        try:
            return call_gemini_flash_planner(user_prompt, system_prompt, [])
        except Exception:
            pass
    return textwrap.dedent(f"""
    **FAB ({lang})**
    - Features: {benefits or '(chưa nhập)'}
    - Advantages: Nổi bật so với lựa chọn khác
    - Benefits: Lợi ích trực tiếp cho khách hàng
    """).strip()

def generate_caption(
    product_desc: str,
    customer: str,
    brand: str,
    lang: str,
    tone: str,
) -> str:
    """
    KHÔNG ẢNH → tạo caption từ mô tả + khách hàng.
    Có Gemini thì ưu tiên gọi; nếu không có -> fallback offline.
    """
    if call_gemini_flash is not None and SystemMessage is not None:
        try:
            user_prompt = f"""
            Create a concise Facebook caption in {lang} with tone {tone}.
            Inputs:
            - Brand: {brand}
            - Product: {product_desc}
            - Customer: {customer}
            Make it short, benefit-oriented, include a clear CTA.
            """
            up, sys_inst = apply_occasion_lock(user_prompt, persona_vi)
            return call_gemini_flash(up, sys_inst, [SystemMessage(persona_vi)])
        except Exception:
            pass

    product_desc = (product_desc or "").strip()
    customer     = (customer or "").strip()
    brand        = (brand or "Tiximax Logistics").strip()
    lang         = (lang or "Tiếng Việt").strip()
    tone         = (tone or "Chuyên nghiệp").strip()

    if lang.lower().startswith("english"):
        return textwrap.dedent(f"""
        **{brand} — Facebook Caption ({tone})**

        - Product: {product_desc or "(n/a)"}
        - Audience: {customer or "(n/a)"}

        Keep it crisp. Highlight authenticity & speed.
        CTA: **Inbox now for a quote!**
        """).strip()

    return textwrap.dedent(f"""
    **{brand} — Gợi ý Caption ({tone})**

    - Sản phẩm: {product_desc or "(chưa nhập)"}
    - Khách hàng: {customer or "(chưa nhập)"}

    Nhấn mạnh hàng chuẩn & giao nhanh.
    CTA: **Nhắn tin ngay để được báo giá!**
    """).strip()

def generate_caption_from_image_and_inputs(
    *,
    features: dict,
    product_desc: str,
    customer: str,
    brand: str,
    lang: str,
    tone: str,
    include_logo_hint: bool = False,
) -> str:
    """
    CÓ ẢNH → caption kết hợp:
      (mô tả + khách hàng) + (đặc trưng ảnh) + (tuỳ chọn) câu nhắc về logo.
    """
    product_desc = (product_desc or "").strip()
    customer     = (customer or "").strip()
    brand        = (brand or "Tiximax Logistics").strip()
    lang         = (lang or "Tiếng Việt").strip()
    tone         = (tone or "Chuyên nghiệp").strip()

    color  = features.get("dominant_color_name", "xanh dương")
    aspect = features.get("aspect_label", "1:1")
    orient = features.get("orientation", "ngang")
    bright = features.get("brightness", "trung tính")
    size_s = f"{features.get('width','?')}×{features.get('height','?')}px"

    logo_line_vi = " Logo thương hiệu đã được chèn tinh tế để tăng nhận diện." if include_logo_hint else ""
    logo_line_en = " Brand logo is subtly overlaid to enhance recognition."     if include_logo_hint else ""

    if lang.lower().startswith("english"):
        lines = [
            f"**{brand} — Image-informed Caption ({tone})**",
            "",
        ]
        if product_desc: lines.append(f"- Product: {product_desc}")
        if customer:     lines.append(f"- Audience: {customer}")
        lines.extend([
            f"- Canvas: {size_s}, aspect {aspect}, {orient} orientation, {bright} lighting",
            f"- Dominant color: {color}",
            "",
            f"Showcase authentic details with a clean {color} vibe and {orient} framing.{logo_line_en}",
            "Keep copy concise, highlight benefits, and add a clear CTA: **Inbox now for a quote!**",
        ])
        return "\n".join(lines).strip()

    lines = [
        f"**{brand} — Caption dựa trên ảnh ({tone})**",
        "",
    ]
    if product_desc: lines.append(f"- Sản phẩm: {product_desc}")
    if customer:     lines.append(f"- Khách hàng: {customer}")
    lines.extend([
        f"- Khung ảnh: {size_s}, tỉ lệ {aspect}, bố cục {orient}, độ sáng {bright}",
        f"- Màu chủ đạo: {color}",
        "",
        f"Nhấn mạnh chi tiết thật, giữ tông {color} chủ đạo và bố cục {orient} gọn gàng.{logo_line_vi}",
        "Viết ngắn gọn, nêu lợi ích rõ và CTA: **Nhắn tin ngay để được báo giá!**",
    ])
    return "\n".join(lines).strip()

def _cg_as_tones_line(tones) -> str:
    if isinstance(tones, (list, tuple)) and tones:
        return ", ".join([str(t) for t in tones if str(t).strip()])
    if isinstance(tones, str) and tones.strip():
        return tones.strip()
    return "Chuyên nghiệp, rõ ràng"

def _cg_parse_outline_from_payload(d: dict) -> list[str]:
    import re as _re
    for key in ("outline_sections", "sections"):
        v = d.get(key)
        if isinstance(v, list):
            cleaned = [str(x).strip() for x in v if str(x).strip()]
            if cleaned:
                return cleaned
    for key in ("outline_text", "outline", "toc", "muc_luc"):
        s = d.get(key)
        if isinstance(s, str) and s.strip():
            items = []
            for ln in s.strip().splitlines():
                item = _re.sub(r'^\s*[\-\*\u2022\u2023\u25E6\d]+[.)]?\s*', "", ln).strip()
                if _re.match(r"(?i)^mục\s*lục$", item):
                    continue
                if item:
                    items.append(item)
            if items:
                return items
    return []

def planner_generate_bounded(payload: dict) -> tuple[dict, int]:
    if resolve_channel is None or build_system_prompt_dynamic is None:
        return {"error": "Planner modules missing. Hãy cài đặt Marketing_Planner/*."}, 500

    d = payload or {}
    lang = (d.get("lang") or "Tiếng Việt").strip()
    tones_line = _cg_as_tones_line(d.get("tones", []))
    include_toc = bool(d.get("include_toc", False))

    meta_title = (d.get("meta_title") or "").strip()
    meta_desc  = (d.get("meta_description") or "").strip()
    slug       = (d.get("slug") or "").strip()

    try:
        target_words = int(d.get("target_words", 2000))
    except Exception:
        target_words = 2000
    try:
        tolerance_pct = int(d.get("tolerance_pct", 6))
    except Exception:
        tolerance_pct = 6

    ch = resolve_channel(d.get("channel", ""))
    if not ch:
        return {"error": "Channel not found"}, 404

    system_prompt = build_system_prompt_dynamic(
        ch=ch,
        lang=lang,
        tones_line=tones_line,
        include_toc=include_toc
    )
    up_body = build_user_prompt_body({
        **d,
        "channel": ch.get("name", ""),
        "include_toc": include_toc
    })


    outline = _cg_parse_outline_from_payload(d)
    t0 = _time.time()
    try:
        text, wc, did_microfix = generate_bounded_longform(
            system_instruction=system_prompt,
            up_body=up_body,
            outline=outline,
            include_toc=include_toc,
            target_words=target_words,
            tolerance_pct=tolerance_pct,
            micro_edit=True
        )
    except Exception as e:
        return {"error": f"LLM error: {e}"}, 500
    latency = round(_time.time() - t0, 2)

    if any([meta_title, meta_desc, slug]):
        text = patch_meta(text, meta_title, meta_desc, slug)

    outline_preview = outline[:10] if outline else []
    return {
        "text": text,
        "meta": {
            "channel_id": ch.get("id"),
            "channel": ch.get("name"),
            "lang": lang,
            "tones": d.get("tones", []) if isinstance(d.get("tones", []), (list, tuple))
                else [d.get("tones")] if d.get("tones") else [],
            "include_toc": include_toc,
            "has_meta_title": bool(meta_title),
            "has_meta_desc": bool(meta_desc),
            "has_slug": bool(slug),
            "target_words": target_words,
            "tolerance_pct": tolerance_pct,
            "latency_sec": latency,
            "used_sectioned_writer": False,
            "outline_cnt": len(outline_preview),
            "outline_preview": outline_preview,
            "word_count_est": wc,
            "micro_edit_applied": did_microfix
        }
    }, 200