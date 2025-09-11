import os, time, re
from flask import Blueprint, render_template, jsonify, request, current_app
from flask import current_app as app
from app.Login.login_required import login_required
from app.Helpers.prompt_KT import persona_vi
from app.Helpers.LLM_client import apply_occasion_lock, call_gemini_flash, call_gemini_flash_planner, extract_image_prompt, ensure_english_prompt
from app.Helpers.Image_generation_and_processing import build_image_prompt, generate_image_via_gemini_api, add_logo_to_images, pil_to_base64, load_default_logo, conform_aspect, ALLOWED_ASPECTS
from app.Helpers.Content_generation import generate_rephrase_content, generate_tiktok_content, generate_fab_content
from app.Helpers.Marketing_Planner.Content_Planner import _describe_builtin_channel, _describe_custom_channel, _normalize_channel, _build_system_prompt_ifelse, build_user_prompt_body
from PIL import Image
from app.Helpers.Marketing_Planner.bounded_writer import generate_bounded_longform
from app.Helpers.Marketing_Planner.text_postprocess import (
    sanitize_blog_article,
    strip_toc_from_output,
    patch_meta,
)
from app.Helpers.Marketing_Planner.channels_store import upsert_channels_from_json
try:
    # from app.Model_LLM.hybrid_retriever import TOP_K
    from app.Helpers.Marketing_Planner.channels_store import list_all_for_planner, load_channels, create_channel, update_channel, delete_channel, get_by_name
except Exception:
    from app.Helpers.Marketing_Planner.channels_store import list_all_for_planner, load_channels, create_channel, update_channel, delete_channel, get_by_name
from app.Helpers.Marketing_Planner.prompt_builder import build_system_prompt_dynamic
from app.Helpers.Marketing_Planner.helpers_resolve import resolve_channel
from app.Helpers.config_MKT import call_text, MAX_TOKENS_MKT
from app.Helpers.Marketing_Planner.llm_longform import generate_longform
from app.Helpers.Marketing_Planner.llm_longform_sectioned import generate_sectioned_longform
bp = Blueprint('marketing', __name__)

# ====== QUAN TRỌNG: quyền ======
# Sales & Manager Sales được dùng toàn bộ tính năng Marketing:
MKT_ROLES = ['marketing', 'sales', 'manager_marketing', 'manager_sales']
# Quản trị Marketing Channels: 2 manager + admin
QL_ROLES = ['admin', 'manager_marketing', 'manager_sales']

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

# ===== APIs =====
@bp.route("/api/fbads/generate_text", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_fb_text():
    data = request.get_json() or {}
    product = data.get("product_desc", "")
    customer = data.get("customer", "")
    lang = data.get("lang", "Tiếng Việt")
    brand = (data.get("brand") or "").strip() or "Tiximax Logistics"
    tone = (data.get("tone") or "Chuyên nghiệp").strip()

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
    * Output only ONE complete piece following the template (Analysis → Campaign Idea → Facebook Post → IMAGE\_PROMPT).

    """.strip()
    u_prompt, sys_inst = apply_occasion_lock(user_prompt, persona_vi)

    try:
        t0 = time.time()
        text = call_gemini_flash(u_prompt, sys_inst, [])
        latency = time.time() - t0
        return jsonify({"text": text, "meta": {"latency_sec": round(latency, 2)}})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo nội dung: {str(e)}"}), 500

@bp.route("/api/fbads/generate_images", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_fb_imgs():
    form_data = request.form
    result_text = form_data.get("result_text", "")
    product = form_data.get("product_desc", "")
    customer = form_data.get("customer", "")
    brand = (form_data.get("brand", "") or "").strip() or "Tiximax Logistics"
    engine_label = form_data.get("engine_label", "Gemini 2.0 Flash")
    aspect = (form_data.get("aspect", "1:1") or "1:1").strip()
    if aspect not in ALLOWED_ASPECTS:
        aspect = "1:1"
    style = form_data.get("style_preset", "Semi-realistic")
    composition = form_data.get("composition", "Lifestyle scene")

    add_logo = form_data.get("add_logo", "false").lower() == "true"
    keep_logo = form_data.get("keep_logo_original", "true").lower() == "true"
    logo_scale = float(form_data.get("logo_scale", 0.15))
    logo_margin = int(form_data.get("logo_margin", 20))

    logo_img = None
    if request.files.get("logo_file"):
        try:
            logo_img = Image.open(request.files["logo_file"].stream).convert("RGBA")
        except Exception:
            logo_img = None
    elif add_logo:
        try:
            logo_img = load_default_logo(current_app.root_path)
        except Exception:
            from PIL import Image as PILImage
            default_path = os.path.join(current_app.root_path, "static", "images", "logo.png")
            if os.path.exists(default_path):
                try:
                    logo_img = PILImage.open(default_path).convert("RGBA")
                except Exception:
                    logo_img = None

    prompt_raw = extract_image_prompt(result_text) if result_text else None
    if not prompt_raw:
        subject = f"{brand} – {product} (audience: {customer})"
        prompt_raw = build_image_prompt(subject=subject, aspect_ratio=aspect, style=style, composition=composition, include_logo=(not add_logo))

    try:
        prompt_en = ensure_english_prompt(prompt_raw)
        engine = "gemini2" if engine_label == "Gemini 2.0 Flash" else "imagen4"
        images = generate_image_via_gemini_api(prompt_en, engine=engine, aspect_ratio=aspect, n_images=2)
        images = [conform_aspect(im, aspect, mode="crop", bg="#FFFFFF") for im in (images or [])]

        if add_logo and images:
            if logo_img is None:
                return jsonify({"error": "Không tìm thấy logo (static/images/logo.png) hoặc file upload."}), 400
            images = add_logo_to_images(images, logo_img, margin=logo_margin, keep_original=keep_logo, scale=logo_scale)

        return jsonify({"images": [pil_to_base64(img) for img in images], "used_prompt": prompt_en})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo ảnh: {str(e)}"}), 500

@bp.route("/api/rephrase", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_rephrase():
    data = request.get_json() or {}
    text_src = data.get("text_src", "")
    lang = data.get("lang", "Tiếng Việt")
    tone = data.get("tone", "Chuyên nghiệp")
    if not text_src.strip():
        return jsonify({"error": "Thiếu văn bản đầu vào."}), 400
    try:
        text = generate_rephrase_content(text_src, lang, tone)
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi viết lại: {str(e)}"}), 500

@bp.route("/api/tiktok", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_tiktok():
    data = request.get_json() or {}
    brief = data.get("brief", "")
    lang = data.get("lang", "Tiếng Việt")
    duration = int(data.get("duration", 20))
    objective = data.get("objective", "Chuyển đổi inbox")
    if not brief.strip():
        return jsonify({"error": "Thiếu nội dung kịch bản."}), 400
    try:
        text = generate_tiktok_content(brief, lang, duration, objective)
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo TikTok content: {str(e)}"}), 500

@bp.route("/api/fab", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_fab():
    data = request.get_json() or {}
    benefits = data.get("benefits", "")
    lang = data.get("lang", "Tiếng Việt")
    extra = data.get("extra", "")
    if not benefits.strip():
        return jsonify({"error": "Thiếu lợi ích sản phẩm/dịch vụ."}), 400
    try:
        text = generate_fab_content(benefits, lang, extra)
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo FAB content: {str(e)}"}), 500

def _merge_channels_for_planner():
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
        key = (c.get('id') or c.get('name') or '').strip().lower()
        if not key or key in seen:
            continue
        if c.get('archived'):
            continue
        merged.append(c)
        seen.add(key)
    return merged

@bp.route("/api/channels", methods=["GET"])
@login_required(roles=MKT_ROLES)
def api_channels_list():
    return jsonify({"items": _merge_channels_for_planner()})

@bp.route("/api/channels/custom", methods=["GET"])
@login_required(roles=QL_ROLES)
def api_channels_list_custom():
    return jsonify({"items": load_channels()})

@bp.route("/api/channels", methods=["POST"])
@login_required(roles=QL_ROLES)
def api_channels_create():
    d = request.get_json(silent=True) or {}
    try:
        item = create_channel(d)
        return jsonify(item), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@bp.route("/api/channels/<cid>", methods=["PUT","PATCH"])
@login_required(roles=QL_ROLES)
def api_channels_update(cid):
    d = request.get_json(silent=True) or {}
    try:
        item = update_channel(cid, d)
        return jsonify(item)
    except KeyError:
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@bp.route("/api/channels/<cid>", methods=["DELETE"])
@login_required(roles=QL_ROLES)
def api_channels_delete(cid):
    try:
        delete_channel(cid)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# @bp.route("/api/channels/prompt", methods=["POST"])
# @login_required(roles=QL_ROLES)
# def api_channels_prompt():
#     d = request.get_json(silent=True) or {}
#     channel_in = d.get("channel", "")
#     lang = d.get("lang", "Tiếng Việt")
#     tones = d.get("tones", [])
#     channel = _normalize_channel(channel_in)
#     ch = get_by_name(channel)
#     desc = _describe_custom_channel(ch, lang) if ch else _describe_builtin_channel(channel, lang)
#     tones_line = ", ".join(tones) if tones else "Chuyên nghiệp, rõ ràng"
#     sys_ask = f"""
#     You are a prompt engineer. Based on the channel specification below,
#     write a concise, production-ready **SYSTEM PROMPT** (in {lang}) for a content generator agent for **Tiximax Logistics**.
#     Requirements:
#     - Start with a 1–2 sentence role definition.
#     - Then 3–8 bullet rules aligned with the channel and this brand voice: {tones_line}.
#     - Include a section "ĐẦU RA (markdown)" that defines the exact output structure.
#     - Do NOT invent pricing/promotions.
#     - Tailor strictly to the channel constraints.
#     Channel specification:
#     {desc}

#     After the SYSTEM PROMPT, also include a short **USER PROMPT (example)**.
#     Format:

#     ### SYSTEM PROMPT
#     ...
#     ### USER PROMPT (example)
#     ...
#     """.strip()

#     try:
#         result = call_gemini_flash_planner(sys_ask, "", [])
#     except Exception as e:
#         return jsonify({"error": f"Lỗi gọi Gemini: {e}"}), 500
#     return jsonify({"channel": channel, "generated": result})

# # === Planner API ===
# @bp.route("/api/planner/generate", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_planner_generate():
#     d = request.get_json(silent=True) or {}
#     goal       = d.get("goal") or (d.get("objectives") or [None])[0]
#     channel_in = d.get("channel", "")
#     channel    = _normalize_channel(channel_in)
#     tones      = d.get("tones", [])
#     lang       = d.get("lang", "Tiếng Việt")

#     system_prompt = _build_system_prompt_ifelse(channel, goal, tones, lang)
#     up_body = build_user_prompt_body({**d, "channel": channel})
#     user_prompt, sys_inst = apply_occasion_lock(up_body, system_prompt)

#     t0 = time.time()
#     try:
#         text = call_gemini_flash_planner(user_prompt, sys_inst, [SystemMessage(persona_vi)])
#     except Exception as e:
#         try:
#             app.logger.exception("Planner LLM error: %s", e)
#         except Exception:
#             pass
#         return jsonify({"error": f"Lỗi LLM: {e}"}), 500
#     dt = time.time() - t0

#     return jsonify({
#         "text": text,
#         "meta": {"latency_sec": round(dt, 2), "channel": channel or "N/A", "goal": goal or "N/A"}
#     })


@bp.route("/api/channels/import", methods=["POST"])
@login_required(roles=QL_ROLES)
def api_channels_import():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Body phải là JSON array các channel"}), 400
    stats = upsert_channels_from_json(data)
    code = 200 if "error" not in stats else 400
    return jsonify({"ok": "error" not in stats, **stats}), code



def _as_tones_line(tones):
    if isinstance(tones, (list, tuple)) and tones:
        return ", ".join([str(t) for t in tones if str(t).strip()])
    if isinstance(tones, str) and tones.strip():
        return tones.strip()
    return "Chuyên nghiệp, rõ ràng"

def _parse_outline_from_payload(d: dict) -> list[str]:
    """
    Bóc outline từ:
      - outline_sections / sections: List[str]
      - outline_text / outline / toc / muc_luc: chuỗi nhiều dòng
    """
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
            items = []
            for ln in lines:
                item = re.sub(r'^\s*[\-\*\u2022\u2023\u25E6\d]+[.)]?\s*', "", ln).strip()
                if re.match(r"(?i)^mục\s*lục$", item):
                    continue
                if item:
                    items.append(item)
            if items:
                return items
    return []

@bp.route("/api/planner/generate", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)
def api_planner_generate():
    d = request.get_json(silent=True) or {}

    # -------- Inputs --------
    lang = (d.get("lang") or "Tiếng Việt").strip()
    tones_line = _as_tones_line(d.get("tones", []))
    include_toc = bool(d.get("include_toc", False))  # mặc định KHÔNG xuất TOC

    # Meta ghim từ payload (nếu có)
    meta_title = (d.get("meta_title") or "").strip()
    meta_desc  = (d.get("meta_description") or "").strip()
    slug       = (d.get("slug") or "").strip()

    # Target words (ưu tiên 2000/±6%)
    try:
        target_words = int(d.get("target_words", 2000))
    except Exception:
        target_words = 2000
    try:
        tolerance_pct = int(d.get("tolerance_pct", 6))
    except Exception:
        tolerance_pct = 6

    # -------- Channel --------
    ch = resolve_channel(d.get("channel", ""))
    if not ch:
        return jsonify({"error": "Channel not found"}), 404

    # -------- SYSTEM PROMPT --------
    system_prompt = build_system_prompt_dynamic(
        ch=ch,
        lang=lang,
        tones_line=tones_line,
        include_toc=include_toc
    )

    # -------- USER PROMPT --------
    up_body = build_user_prompt_body({
        **d,
        "channel": ch.get("name", ""),
        "include_toc": include_toc
    })

    # -------- Outline (nếu có) --------
    outline = _parse_outline_from_payload(d)

    # -------- Gọi LLM (bounded) --------
    t0 = time.time()
    text, wc, did_microfix = generate_bounded_longform(
        system_instruction=system_prompt,
        up_body=up_body,
        outline=outline,
        include_toc=include_toc,
        target_words=target_words,    # nên mặc định 2000
        tolerance_pct=tolerance_pct,  # nên mặc định 6
        micro_edit=True
    )
    latency = round(time.time() - t0, 2)
    used_sectioned = False  # bounded-writer không đi từng mục

    # -------- Hậu xử lý cuối --------
    if any([meta_title, meta_desc, slug]):
        text = patch_meta(text, meta_title, meta_desc, slug)

    # -------- Response --------
    outline_preview = outline[:10] if outline else []
    return jsonify({
        "text": text,
        "meta": {
            "channel_id": ch.get("id"),
            "channel": ch.get("name"),
            "lang": lang,
            "tones": d.get("tones", []) if isinstance(d.get("tones", []), (list, tuple)) else [d.get("tones")] if d.get("tones") else [],
            "include_toc": include_toc,
            "has_meta_title": bool(meta_title),
            "has_meta_desc": bool(meta_desc),
            "has_slug": bool(slug),
            "target_words": target_words,
            "tolerance_pct": tolerance_pct,
            "latency_sec": latency,
            "used_sectioned_writer": used_sectioned,
            "outline_cnt": len(outline_preview),
            "outline_preview": outline_preview,
            "word_count_est": wc,
            "micro_edit_applied": did_microfix
        }
    })
