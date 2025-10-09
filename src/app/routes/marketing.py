from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, render_template, jsonify, request, current_app
from app.Login.login_required import login_required

# LLM helpers (tuỳ dự án bạn đã có sẵn)
from app.Helpers.prompt_KT import persona_vi
from app.Helpers.LLM_client import (
    apply_occasion_lock,
    call_gemini_flash,
    extract_image_prompt,
    ensure_english_prompt,
)
from app.Helpers.Image_generation_and_processing import (
    build_image_prompt,
    generate_image_via_gemini_api,
    add_logo_to_images,
    pil_to_base64,
    load_default_logo,
    conform_aspect,
    ALLOWED_ASPECTS,
)
from app.Helpers.Content_generation import (
    generate_rephrase_content,
    generate_tiktok_content,
    generate_fab_content,
)

# Marketing Planner (phiên bản của bạn)
from app.Helpers.Marketing_Planner.Content_Planner import build_user_prompt_body
from app.Helpers.Marketing_Planner.bounded_writer import generate_bounded_longform
from app.Helpers.Marketing_Planner.text_postprocess import patch_meta
from app.Helpers.Marketing_Planner.channels_store import upsert_channels_from_json
try:
    from app.Helpers.Marketing_Planner.channels_store import (
        list_all_for_planner, load_channels, create_channel,
        update_channel, delete_channel,
    )
except Exception:
    from app.Helpers.Marketing_Planner.channels_store import (
        list_all_for_planner, load_channels, create_channel,
        update_channel, delete_channel,
    )
from app.Helpers.Marketing_Planner.prompt_builder import build_system_prompt_dynamic
from app.Helpers.Marketing_Planner.helpers_resolve import resolve_channel

from PIL import Image

bp = Blueprint("marketing", __name__)

MKT_ROLES = ["marketing", "sales", "manager_marketing", "manager_sales"]
QL_ROLES  = ["admin", "manager_marketing", "manager_sales"]

# ===== Pages =====
@bp.route("/marketing/rephrase")
@login_required(roles=MKT_ROLES)
def page_rephrase():
    return render_template("marketing/rephrase.html")

@bp.route("/marketing/tiktok")
@login_required(roles=MKT_ROLES)
def page_tiktok():
    return render_template("marketing/tiktok.html")

@bp.route("/marketing/fab")
@login_required(roles=MKT_ROLES)
def page_fab():
    return render_template("marketing/fab.html")

@bp.route("/marketing/planner")
@login_required(roles=MKT_ROLES)
def marketing_planner():
    return render_template("marketing/planner.html", active="marketing")

@bp.route("/marketing/channels")
@login_required(roles=QL_ROLES)
def marketing_channels():
    return render_template("marketing/channels.html", active="marketing")

# ===== APIs khác (FB Ads / Images / Rephrase / TikTok / FAB) =====
@bp.route("/api/fbads/generate_text", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_fb_text():
    data = request.get_json(silent=True) or {}
    product  = (data.get("product_desc") or "").strip()
    customer = (data.get("customer") or "").strip()
    lang     = (data.get("lang") or "Tiếng Việt").strip()
    brand    = (data.get("brand") or "").strip() or "Tiximax Logistics"
    tone     = (data.get("tone") or "Chuyên nghiệp").strip()
    if not product or not customer:
        return jsonify({"error": "Thiếu dữ liệu bắt buộc."}), 400

    user_prompt = f"""
        Create marketing content using the fixed template below for a Facebook Ads campaign.
        Language: {lang}
        Brand: {brand}
        Tone/Brand voice: {tone}

        Input:
        * Product description: {product}
        * Customer persona: {customer}

        REQUIREMENTS:
        * Faithfully reflect the specified brand voice (tone).
        * Do not invent promotions/prices if none are provided.
        * Output only ONE complete piece following the template (Analysis → Campaign Idea → Facebook Post → IMAGE_PROMPT).
        """.strip()

    u_prompt, sys_inst = apply_occasion_lock(user_prompt, persona_vi)
    try:
        t0 = time.perf_counter()
        text = call_gemini_flash(u_prompt, sys_inst, [])
        latency = round(time.perf_counter() - t0, 2)
        return jsonify({"text": text, "meta": {"latency_sec": latency}})
    except Exception as e:
        current_app.logger.exception("api_fb_text error: %s", e)
        return jsonify({"error": f"Lỗi khi tạo nội dung: {e}"}), 500


@bp.route("/api/fbads/generate_images", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_fb_imgs():
    form_data   = request.form
    result_text = (form_data.get("result_text") or "").strip()
    product     = (form_data.get("product_desc") or "").strip()
    customer    = (form_data.get("customer") or "").strip()
    brand       = (form_data.get("brand") or "").strip() or "Tiximax Logistics"
    engine_label= (form_data.get("engine_label") or "Gemini 2.0 Flash").strip()
    aspect      = (form_data.get("aspect") or "1:1").strip()
    if aspect not in ALLOWED_ASPECTS:
        aspect = "1:1"
    style       = (form_data.get("style_preset") or "Semi-realistic").strip()
    composition = (form_data.get("composition") or "Lifestyle scene").strip()

    add_logo   = (form_data.get("add_logo") or "false").lower() == "true"
    keep_logo  = (form_data.get("keep_logo_original") or "true").lower() == "true"
    logo_scale = float(form_data.get("logo_scale") or 0.15)
    logo_margin= int(form_data.get("logo_margin") or 20)

    logo_img: Optional[Image.Image] = None
    if "logo_file" in request.files:
        try:
            logo_img = Image.open(request.files["logo_file"].stream).convert("RGBA")
        except Exception:
            logo_img = None
    elif add_logo:
        try:
            logo_img = load_default_logo(current_app.root_path)
        except Exception:
            default_path = os.path.join(current_app.root_path, "static", "images", "logo.png")
            if os.path.exists(default_path):
                try:
                    logo_img = Image.open(default_path).convert("RGBA")
                except Exception:
                    logo_img = None

    prompt_raw = extract_image_prompt(result_text) if result_text else None
    if not prompt_raw:
        subject = f"{brand} – {product} (audience: {customer})"
        prompt_raw = build_image_prompt(
            subject=subject,
            aspect_ratio=aspect,
            style=style,
            composition=composition,
            include_logo=(not add_logo),
        )

    try:
        prompt_en = ensure_english_prompt(prompt_raw)
        engine = "gemini2" if engine_label == "Gemini 2.0 Flash" else "imagen4"
        images = generate_image_via_gemini_api(prompt_en, engine=engine, aspect_ratio=aspect, n_images=2) or []
        images = [conform_aspect(im, aspect, mode="crop", bg="#FFFFFF") for im in images]

        if add_logo and images:
            if logo_img is None:
                return jsonify({"error": "Không tìm thấy logo (static/images/logo.png) hoặc file upload."}), 400
            images = add_logo_to_images(images, logo_img, margin=logo_margin, keep_original=keep_logo, scale=logo_scale)

        return jsonify({"images": [pil_to_base64(img) for img in images], "used_prompt": prompt_en})
    except Exception as e:
        current_app.logger.exception("api_fb_imgs error: %s", e)
        return jsonify({"error": f"Lỗi khi tạo ảnh: {e}"}), 500


@bp.route("/api/rephrase", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_rephrase():
    data = request.get_json(silent=True) or {}
    text_src = (data.get("text_src") or "").strip()
    lang     = (data.get("lang") or "Tiếng Việt").strip()
    tone     = (data.get("tone") or "Chuyên nghiệp").strip()
    if not text_src:
        return jsonify({"error": "Thiếu văn bản đầu vào."}), 400
    try:
        text = generate_rephrase_content(text_src, lang, tone)
        return jsonify({"text": text})
    except Exception as e:
        current_app.logger.exception("api_rephrase error: %s", e)
        return jsonify({"error": f"Lỗi khi viết lại: {e}"}), 500


@bp.route("/api/tiktok", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_tiktok():
    data      = request.get_json(silent=True) or {}
    brief     = (data.get("brief") or "").strip()
    lang      = (data.get("lang") or "Tiếng Việt").strip()
    duration  = int(data.get("duration") or 20)
    objective = (data.get("objective") or "Chuyển đổi inbox").strip()
    if not brief:
        return jsonify({"error": "Thiếu nội dung kịch bản."}), 400
    try:
        text = generate_tiktok_content(brief, lang, duration, objective)
        return jsonify({"text": text})
    except Exception as e:
        current_app.logger.exception("api_tiktok error: %s", e)
        return jsonify({"error": f"Lỗi khi tạo TikTok content: {e}"}), 500


@bp.route("/api/fab", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_fab():
    data     = request.get_json(silent=True) or {}
    benefits = (data.get("benefits") or "").strip()
    lang     = (data.get("lang") or "Tiếng Việt").strip()
    extra    = (data.get("extra") or "").strip()
    if not benefits:
        return jsonify({"error": "Thiếu lợi ích sản phẩm/dịch vụ."}), 400
    try:
        text = generate_fab_content(benefits, lang, extra)
        return jsonify({"text": text})
    except Exception as e:
        current_app.logger.exception("api_fab error: %s", e)
        return jsonify({"error": f"Lỗi khi tạo FAB content: {e}"}), 500

# ===== Channels merge + CRUD =====
def _merge_channels_for_planner() -> List[dict]:
    try:
        builtin = list_all_for_planner() or []
    except Exception:
        builtin = []
    try:
        custom = load_channels() or []
    except Exception:
        custom = []
    seen, merged = set(), []
    for c in (builtin + custom):
        key = (c.get("id") or c.get("name") or "").strip().lower()
        if not key or key in seen:
            continue
        if c.get("archived"):
            continue
        merged.append(c)
        seen.add(key)
    return merged

@bp.route("/api/channels", methods=["GET"])
@bp.route("/marketing/api/channels", methods=["GET"])
@login_required(roles=MKT_ROLES)
def api_channels_list():
    return jsonify({"items": _merge_channels_for_planner()})

@bp.route("/api/channels/custom", methods=["GET"])
@bp.route("/marketing/api/channels/custom", methods=["GET"])
@login_required(roles=QL_ROLES)
def api_channels_list_custom():
    return jsonify({"items": load_channels()})

@bp.route("/api/channels", methods=["POST"])
@bp.route("/marketing/api/channels", methods=["POST"])
@login_required(roles=QL_ROLES)
def api_channels_create():
    d = request.get_json(silent=True) or {}
    try:
        item = create_channel(d)
        return jsonify(item), 201
    except Exception as e:
        current_app.logger.exception("api_channels_create error: %s", e)
        return jsonify({"error": str(e)}), 400

@bp.route("/api/channels/<cid>", methods=["PUT", "PATCH"])
@bp.route("/marketing/api/channels/<cid>", methods=["PUT", "PATCH"])
@login_required(roles=QL_ROLES)
def api_channels_update(cid: str):
    d = request.get_json(silent=True) or {}
    try:
        item = update_channel(cid, d)
        return jsonify(item)
    except KeyError:
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        current_app.logger.exception("api_channels_update error: %s", e)
        return jsonify({"error": str(e)}), 400

@bp.route("/api/channels/<cid>", methods=["DELETE"])
@bp.route("/marketing/api/channels/<cid>", methods=["DELETE"])
@login_required(roles=QL_ROLES)
def api_channels_delete(cid: str):
    try:
        delete_channel(cid)
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.exception("api_channels_delete error: %s", e)
        return jsonify({"error": str(e)}), 400

@bp.route("/api/channels/import", methods=["POST"])
@bp.route("/marketing/api/channels/import", methods=["POST"])
@login_required(roles=QL_ROLES)
def api_channels_import():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Body phải là JSON array các channel"}), 400
    stats = upsert_channels_from_json(data)
    code = 200 if "error" not in stats else 400
    return jsonify({"ok": "error" not in stats, **stats}), code

# ===== Planner =====
def _as_tones_line(tones: Any) -> str:
    if isinstance(tones, (list, tuple)) and tones:
        return ", ".join([str(t).strip() for t in tones if str(t).strip()])
    if isinstance(tones, str) and tones.strip():
        return tones.strip()
    return "Chuyên nghiệp, rõ ràng"

def _parse_outline_from_payload(d: dict) -> List[str]:
    for key in ("outline_sections", "sections"):
        v = d.get(key)
        if isinstance(v, list):
            cleaned = [str(x).strip() for x in v if str(x).strip()]
            if cleaned:
                return cleaned
    for key in ("outline_text", "outline", "toc", "muc_luc"):
        s = d.get(key)
        if isinstance(s, str) and s.strip():
            lines = s.strip().splitlines()
            items: List[str] = []
            for ln in lines:
                item = re.sub(r"^\s*[\-\*\u2022\u2023\u25E6\d]+[.)]?\s*", "", ln).strip()
                if re.match(r"(?i)^mục\s*lục$", item):
                    continue
                if item:
                    items.append(item)
            if items:
                return items
    return []

def _resolve_target_from_length(length_line: str) -> Tuple[int, int]:
    s = (length_line or "").lower()
    if "ngắn" in s or "150" in s:
        return 150, 4
    if "trung" in s or "300" in s or "500" in s:
        return 400, 6
    if "dài" in s or "800" in s:
        return 900, 6
    if "seo" in s or "2000" in s:
        return 2000, 6
    return 400, 6

def _strip_meta_headings(md: str) -> str:
    # Tuỳ chọn: bỏ các heading Meta trong thân bài nếu không muốn hiển thị
    pat = re.compile(r"^##\s*(Meta Title|Meta Description|URL Slug)\b[\s\S]*?(?=^\S|\Z)", re.M)
    out = pat.sub("", md or "").strip()
    return out

@bp.route("/api/planner/generate", methods=["POST"])
@bp.route("/marketing/api/planner/generate", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_planner_generate():
    d: Dict[str, Any] = request.get_json(silent=True) or {}

    # -------- Inputs --------
    lang        = (d.get("lang") or "Tiếng Việt").strip()
    tones_line  = _as_tones_line(d.get("tones", []))
    include_toc = bool(d.get("include_toc", False))  # mặc định KHÔNG xuất TOC

    # Meta ghim từ payload (nếu có)
    meta_title  = (d.get("meta_title") or "").strip()
    meta_desc   = (d.get("meta_description") or "").strip()
    slug        = (d.get("slug") or "").strip()

    # -------- Channel --------
    ch = resolve_channel(d.get("channel", ""))
    if not ch:
        return jsonify({"error": "Channel not found"}), 404

    # -------- target_words / tolerance từ FE hoặc từ 'length' --------
    length_line = (d.get("length") or "").strip().lower()
    try:
        req_target = int(d.get("target_words"))  # FE gửi
    except Exception:
        req_target = None
    if not req_target:
        req_target, _tol = _resolve_target_from_length(length_line)

    try:
        tolerance_pct = int(d.get("tolerance_pct", 6))
    except Exception:
        # nếu FE không gửi tolerance thì map theo length
        _, tolerance_pct = _resolve_target_from_length(length_line)

    # GHIM vào payload để build_user_prompt_body dùng cùng con số này
    d["target_words"] = req_target

    # -------- SYSTEM PROMPT --------
    system_prompt = build_system_prompt_dynamic(
        ch=ch,
        lang=lang,
        tones_line=tones_line,
        include_toc=include_toc,
    )

    # -------- USER PROMPT --------
    up_body = build_user_prompt_body({
        **d,
        "channel": ch.get("name", ""),
        "include_toc": include_toc,
    })

    # -------- Outline (nếu có) --------
    outline = _parse_outline_from_payload(d)

    # -------- Gọi LLM (bounded) --------
    t0 = time.perf_counter()
    try:
        text, wc, did_microfix = generate_bounded_longform(
            system_instruction=system_prompt,
            up_body=up_body,
            outline=outline,
            include_toc=include_toc,
            target_words=req_target,       # <<< QUAN TRỌNG
            tolerance_pct=tolerance_pct,   # <<< QUAN TRỌNG
            micro_edit=True,
        )
    except Exception as e:
        current_app.logger.exception("api_planner_generate bounded_writer error: %s", e)
        return jsonify({"error": f"Lỗi LLM: {e}"}), 500
    latency = round(time.perf_counter() - t0, 2)

    # (Tuỳ chọn) loại các heading Meta ở đầu thân bài
    try:
        text = _strip_meta_headings(text)
    except Exception:
        pass

    # -------- Hậu xử lý cuối (ghim meta nếu truyền) --------
    if any([meta_title, meta_desc, slug]):
        try:
            text = patch_meta(text, meta_title, meta_desc, slug)
        except Exception:
            pass

    # -------- Response --------
    outline_preview = outline[:10] if outline else []
    return jsonify({
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
            "target_words": req_target,
            "tolerance_pct": tolerance_pct,
            "latency_sec": latency,
            "outline_cnt": len(outline_preview),
            "outline_preview": outline_preview,
            "word_count_est": wc,
            "micro_edit_applied": did_microfix,
        }
    })
