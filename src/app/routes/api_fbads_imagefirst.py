# app/routes/api_fbads_imagefirst.py
from __future__ import annotations
from flask import Blueprint, request, jsonify, current_app
from app.Login.login_required import login_required
from app.Helpers.Image_generation_and_processing import (
    overlay_exact_from_upload,
    generate_image_simple_fallback,
    file_storage_to_pil,
    analyze_image_features,
)

from app.Helpers.Content_generation import (
    generate_caption,                         
    generate_caption_from_image_and_inputs,
)

bp = Blueprint("fbads_imagefirst", __name__)

@bp.route("/api/fbads/image_exact", methods=["POST"])
def api_image_exact():
    """
    CÓ ẢNH → GHÉP LOGO (giữ nguyên ảnh).
    """
    image_file = request.files.get("image_file")
    if not image_file:
        return jsonify({"ok": False, "error": "Thiếu image_file"}), 400
    try:
        b64, meta = overlay_exact_from_upload(
            image_file=image_file,
            add_logo=(request.form.get("add_logo", "true").lower() in ("1","true","yes")),
            logo_file=request.files.get("logo_file"),
            logo_scale=float(request.form.get("logo_scale", "0.15")),
            logo_margin=int(request.form.get("logo_margin", "20")),
            logo_pos=(request.form.get("logo_pos") or "br"),
            output_format=(request.form.get("output_format") or None),
            app_root_path=current_app.root_path,
        )
        return jsonify({"ok": True, "text": "", "images": [b64], "meta": meta})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/fbads/generate_text_from_image", methods=["POST"])
def api_generate_text_from_image():
    """
    CÓ ẢNH → phân tích ảnh + kết hợp mô tả/khách hàng → tạo caption.
    Input (form-data):
      - image_file (bắt buộc)
      - product_desc, customer, brand, lang, tone (tùy chọn)
      - add_logo (tùy chọn) → nếu true, thêm câu nhắc về logo trong caption
    """
    image_file = request.files.get("image_file")
    if not image_file:
        return jsonify({"ok": False, "error": "Thiếu image_file"}), 400
    try:
        img = file_storage_to_pil(image_file)
        if img is None:
            return jsonify({"ok": False, "error": "Ảnh không hợp lệ"}), 400

        feats = analyze_image_features(img)
        text = generate_caption_from_image_and_inputs(
            features=feats,
            product_desc=(request.form.get("product_desc") or ""),
            customer=(request.form.get("customer") or ""),
            brand=(request.form.get("brand") or "Tiximax Logistics"),
            lang=(request.form.get("lang") or "Tiếng Việt"),
            tone=(request.form.get("tone") or "Chuyên nghiệp"),
            include_logo_hint=(request.form.get("add_logo","true").lower() in ("1","true","yes")),
        )
        return jsonify({"ok": True, "text": text, "features": feats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/fbads/generate_text", methods=["POST"])
def api_generate_text():
    """
    KHÔNG ẢNH → caption từ mô tả + khách hàng (giữ như cũ).
    """
    data = request.get_json(silent=True) or {}
    text = generate_caption(
        product_desc=data.get("product_desc", ""),
        customer=data.get("customer", ""),
        brand=data.get("brand", "Tiximax Logistics"),
        lang=data.get("lang", "Tiếng Việt"),
        tone=data.get("tone", "Chuyên nghiệp"),
    )
    return jsonify({"ok": True, "text": text})


@bp.route("/api/fbads/generate_images", methods=["POST"])
def api_generate_images():
    """
    KHÔNG ẢNH → tạo ảnh mới (demo) + (tuỳ chọn) logo.
    """
    try:
        idea_text = (request.form.get("idea_text") or "").strip()
        b64, meta = generate_image_simple_fallback(
            idea_text=idea_text,
            aspect=(request.form.get("aspect") or "1:1").strip(),
            add_logo=(request.form.get("add_logo", "true").lower() in ("1","true","yes")),
            logo_file=request.files.get("logo_file"),
            logo_scale=float(request.form.get("logo_scale", "0.15")),
            logo_margin=int(request.form.get("logo_margin", "20")),
            logo_pos=(request.form.get("logo_pos") or "br"),
            app_root_path=current_app.root_path,
            output_format="png",
        )
        return jsonify({"ok": True, "images": [b64], "used_prompt": idea_text, "meta": meta})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --- Helpers only for the new endpoint ---
import time

def _build_visual_hint(features: dict, lang: str) -> str:
    """Đổi đặc trưng ảnh thành gợi ý ngữ cảnh để nhúng vào prompt text."""
    w = features.get("width"); h = features.get("height")
    aspect = features.get("aspect_label"); orient = features.get("orientation")
    color = features.get("dominant_color_name"); bright = features.get("brightness")
    if (lang or "").lower().startswith("english"):
        return (
            "Image cues (use as creative guidance, do NOT over-describe):\n"
            f"- Canvas: {w}x{h}px, aspect {aspect}, {orient} orientation, {bright} lighting\n"
            f"- Dominant color: {color}"
        )
    return (
        "Gợi ý từ ảnh (định hướng nội dung, không miêu tả quá chi tiết):\n"
        f"- Khung: {w}x{h}px, tỉ lệ {aspect}, bố cục {orient}, độ sáng {bright}\n"
        f"- Màu chủ đạo: {color}"
    )


MKT_ROLES = ['marketing', 'sales', 'manager_marketing', 'manager_sales']
@bp.route("/api/fbads/text_from_image_v2", methods=["POST"])
@login_required(api=True, roles=MKT_ROLES)  # dùng decor/roles y như các route khác
def api_fb_text_from_image_v2():
    """CÓ ẢNH → phân tích ảnh → gọi cùng logic như /api/fbads/generate_text để ra đúng format."""
    image_file = request.files.get("image_file")
    if not image_file:
        return jsonify({"error": "Thiếu image_file"}), 400

    form = request.form
    product  = form.get("product_desc", "")
    customer = form.get("customer", "")
    lang     = form.get("lang", "Tiếng Việt")
    brand    = (form.get("brand") or "").strip() or "Tiximax Logistics"
    tone     = (form.get("tone") or "Chuyên nghiệp").strip()

    if not product or not customer:
        return jsonify({"error": "Thiếu dữ liệu bắt buộc (product_desc, customer)."}), 400

    try:
        # 1) Phân tích ảnh
        from app.Helpers.Image_generation_and_processing import file_storage_to_pil, analyze_image_features
        img = file_storage_to_pil(image_file)
        if img is None:
            return jsonify({"error": "Ảnh không hợp lệ"}), 400
        feats = analyze_image_features(img)
        visual_hint = _build_visual_hint(feats, lang)

        # 2) Gọi cùng “logic” như api_fb_text (không sửa api cũ)
        from app.Helpers.LLM_client import apply_occasion_lock, call_gemini_flash
        from app.Helpers.prompt_KT import persona_vi

        user_prompt = f"""
        Create marketing content using the fixed template below for a Facebook Ads campaign.
        Language: {lang}
        Brand: {brand}
        Tone/Brand voice: {tone}

        Input:
        * Product description: {product}
        * Customer persona: {customer}

        VISUAL_REFERENCE:
        {visual_hint}

        REQUIREMENTS:
        * Faithfully reflect the specified brand voice (tone).
        * Do not invent promotions/prices if none are provided.
        * Output only ONE complete piece following the template (Analysis → Campaign Idea → Facebook Post → IMAGE_PROMPT).
        """.strip()

        u_prompt, sys_inst = apply_occasion_lock(user_prompt, persona_vi)
        t0 = time.time()
        text = call_gemini_flash(u_prompt, sys_inst, [])
        latency = round(time.time() - t0, 2)

        return jsonify({"text": text, "features": feats, "meta": {"latency_sec": latency, "from": "image_v2"}})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo nội dung từ ảnh: {str(e)}"}), 500
