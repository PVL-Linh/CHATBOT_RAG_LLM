import os, time
from flask import Blueprint, render_template, jsonify, request, session, current_app
from app.Login.login_required import login_required
from app.Helpers.prompt_KT import persona_vi
from app.Helpers.LLM_client import apply_occasion_lock, call_gemini_flash, extract_image_prompt, ensure_english_prompt
from app.Helpers.Image_generation_and_processing import build_image_prompt, generate_image_via_gemini_api, add_logo_to_images, pil_to_base64, load_default_logo, conform_aspect, ALLOWED_ASPECTS
from app.Helpers.Content_generation import generate_facebook_ads_content, generate_rephrase_content, generate_tiktok_content, generate_fab_content
from app.Helpers.Marketing_Planner.Content_Planner import _describe_builtin_channel, _describe_custom_channel, _normalize_channel, _build_system_prompt_ifelse, build_user_prompt_body
from PIL import Image
from langchain_core.messages import SystemMessage

try:
    from app.Model_LLM.hybrid_retriever import rerank, TOP_K # not used here actually
    from app.Helpers.Marketing_Planner.channels_store import list_all_for_planner, load_channels, create_channel, update_channel, delete_channel, get_by_name
except Exception:
    from app.Helpers.Marketing_Planner.channels_store import list_all_for_planner, load_channels, create_channel, update_channel, delete_channel, get_by_name

bp = Blueprint('marketing', __name__)

# ===== Pages =====
@bp.route("/marketing/rephrase")
@login_required(roles=['marketing', 'manager_marketing'])
def page_rephrase():
    return render_template("marketing/rephrase.html")

@bp.route("/marketing/tiktok")
@login_required(roles=['marketing', 'manager_marketing'])
def page_tiktok():
    return render_template("marketing/tiktok.html")

@bp.route("/marketing/fab")
@login_required(roles=['marketing', 'manager_marketing'])
def page_fab():
    return render_template("marketing/fab.html")

@bp.route("/marketing/planner")
@login_required(roles=['marketing', 'manager_marketing'])
def marketing_planner():
    return render_template("marketing/planner.html", active="marketing")

@bp.route("/marketing/channels")
@login_required(roles=['admin', 'manager_marketing'])
def marketing_channels():
    return render_template("marketing/channels.html", active="marketing")

# ===== APIs =====
@bp.route("/api/fbads/generate_text", methods=["POST"])
@login_required(api=True, roles=['marketing','manager_marketing'])
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
    Tạo nội dung truyền thông theo mẫu cố định bên dưới cho chiến dịch Facebook Ads.
    Ngôn ngữ: {lang}.
    Thương hiệu: {brand}
    Tone giọng/Brand voice: {tone}


    Thông tin đầu vào:
    - Mô tả sản phẩm: {product}
    - Chân dung khách hàng: {customer}


    YÊU CẦU:
    - Phản ánh đúng giọng thương hiệu (tone) đã nêu.
    - Không bịa khuyến mãi/giá nếu không có.
    - Chỉ xuất MỘT bài hoàn chỉnh đúng template (Phân tích → Ý tưởng chiến dịch → Kịch bản video → Bài viết cho Facebook → IMAGE_PROMPT).
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
@login_required(api=True, roles=['marketing','manager_marketing'])
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
@login_required(api=True, roles=['marketing','manager_marketing'])
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
@login_required(api=True, roles=['marketing','manager_marketing'])
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
@login_required(api=True, roles=['marketing', 'manager_marketing'])
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
@login_required(roles=['marketing', 'manager_marketing'])
def api_channels_list():
    return jsonify({"items": _merge_channels_for_planner()})


@bp.route("/api/channels/custom", methods=["GET"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_list_custom():
    return jsonify({"items": load_channels()})

@bp.route("/api/channels", methods=["POST"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_create():
    d = request.get_json(silent=True) or {}
    try:
        item = create_channel(d)
        return jsonify(item), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
@bp.route("/api/channels/<cid>", methods=["PUT","PATCH"])
@login_required(roles=['admin', 'manager_marketing'])
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
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_delete(cid):
    try:
        delete_channel(cid)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
@bp.route("/api/channels/prompt", methods=["POST"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_prompt():
    d = request.get_json(silent=True) or {}
    channel_in = d.get("channel", "")
    lang = d.get("lang", "Tiếng Việt")
    tones = d.get("tones", [])
    channel = _normalize_channel(channel_in)
    ch = get_by_name(channel)
    desc = _describe_custom_channel(ch, lang) if ch else _describe_builtin_channel(channel, lang)
    tones_line = ", ".join(tones) if tones else "Chuyên nghiệp, rõ ràng"
    sys_ask = f"""
    You are a prompt engineer. Based on the channel specification below,
    write a concise, production-ready **SYSTEM PROMPT** (in {lang}) for a content generator agent for **Tiximax Logistics**.
    Requirements:
    - Start with a 1–2 sentence role definition.
    - Then 3–8 bullet rules aligned with the channel and this brand voice: {tones_line}.
    - Include a section "ĐẦU RA (markdown)" that defines the exact output structure.
    - Do NOT invent pricing/promotions.
    - Tailor strictly to the channel constraints.
    Channel specification:
    {desc}

    After the SYSTEM PROMPT, also include a short **USER PROMPT (example)**.
    Format:

    ### SYSTEM PROMPT
    ...
    ### USER PROMPT (example)
    ...
    """.strip()

    try:
        result = call_gemini_flash(sys_ask, "", [])
    except Exception as e:
        return jsonify({"error": f"Lỗi gọi Gemini: {e}"}), 500
    return jsonify({"channel": channel, "generated": result})

# === Planner API ===
@bp.route("/api/planner/generate", methods=["POST"])
@login_required(api=True, roles=['marketing', 'manager_marketing'])
def api_planner_generate():
    import time
    from langchain_core.messages import SystemMessage
    from Helpers.prompt_KT import persona_vi
    from Helpers.LLM_client import apply_occasion_lock, call_gemini_flash
    from flask import current_app as app

    d = request.get_json(silent=True) or {}
    goal       = d.get("goal") or (d.get("objectives") or [None])[0]
    channel_in = d.get("channel", "")
    channel    = _normalize_channel(channel_in)
    tones      = d.get("tones", [])
    lang       = d.get("lang", "Tiếng Việt")

    system_prompt = _build_system_prompt_ifelse(channel, goal, tones, lang)
    up_body = build_user_prompt_body({**d, "channel": channel})
    user_prompt, sys_inst = apply_occasion_lock(up_body, system_prompt)

    t0 = time.time()
    try:
        text = call_gemini_flash(user_prompt, sys_inst, [SystemMessage(persona_vi)])
    except Exception as e:
        # log ra console để dễ debug
        try:
            app.logger.exception("Planner LLM error: %s", e)
        except Exception:
            pass
        return jsonify({"error": f"Lỗi LLM: {e}"}), 500
    dt = time.time() - t0

    return jsonify({
        "text": text,
        "meta": {"latency_sec": round(dt, 2), "channel": channel or "N/A", "goal": goal or "N/A"}
    })
