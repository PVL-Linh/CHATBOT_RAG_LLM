# import os, time, re
# from pathlib import Path
# from typing import Any, List, Tuple, Dict, Optional
# from flask import Blueprint, json, render_template, jsonify, request, current_app
# from flask import current_app as app
# from app.Login.login_required import login_required
# from app.Helpers.prompt_KT import persona_vi
# from app.Helpers.LLM_client import apply_occasion_lock, call_gemini_flash, call_gemini_flash_planner, extract_image_prompt, ensure_english_prompt
# from app.Helpers.Image_generation_and_processing import build_image_prompt, generate_image_via_gemini_api, add_logo_to_images, pil_to_base64, load_default_logo, conform_aspect, ALLOWED_ASPECTS
# from app.Helpers.Content_generation import generate_rephrase_content, generate_tiktok_content, generate_fab_content
# # from app.Helpers.Marketing_Planner.Content_Planner import _describe_builtin_channel, _describe_custom_channel, _normalize_channel, _build_system_prompt_ifelse, build_user_prompt_body
# from PIL import Image
# from app.Helpers.Marketing_Planner.bounded_writer import generate_bounded_longform
# from app.Helpers.Marketing_Planner.text_postprocess import (
#     sanitize_blog_article,
#     strip_toc_from_output,
#     patch_meta,
#     truncate_words,
# )
# from app.Helpers.Marketing_Planner.channels_store import upsert_channels_from_json
# from app.Helpers.Marketing_Planner.Content_Planner import build_user_prompt_body
# try:
#     # from app.Model_LLM.hybrid_retriever import TOP_K
#     from app.Helpers.Marketing_Planner.channels_store import list_all_for_planner, load_channels, create_channel, update_channel, delete_channel, get_by_name
# except Exception:
#     from app.Helpers.Marketing_Planner.channels_store import list_all_for_planner, load_channels, create_channel, update_channel, delete_channel, get_by_name
# from app.Helpers.Marketing_Planner.prompt_builder import build_system_prompt_dynamic
# from app.Helpers.Marketing_Planner.helpers_resolve import resolve_channel
# from app.Helpers.config_MKT import call_text, MAX_TOKENS_MKT
# from app.Helpers.Marketing_Planner.llm_longform import generate_longform
# from app.Helpers.Marketing_Planner.llm_longform_sectioned import generate_sectioned_longform
# from app.Helpers.Marketing_Planner.short_writer import generate_shortform_compact, generate_shortform_one_shot
# from app.Helpers.Marketing_Planner.text_postprocess import patch_meta, truncate_words

# bp = Blueprint('marketing', __name__)

# # ====== QUAN TRỌNG: quyền ======
# # Sales & Manager Sales được dùng toàn bộ tính năng Marketing:
# MKT_ROLES = ['marketing', 'sales', 'manager_marketing', 'manager_sales']
# # Quản trị Marketing Channels: 2 manager + admin
# QL_ROLES = ['admin', 'manager_marketing', 'manager_sales']

# # ===== Pages =====
# @bp.route("/marketing/rephrase")
# @login_required(roles=MKT_ROLES)
# def page_rephrase():
#     return render_template("marketing/rephrase.html")

# @bp.route("/marketing/tiktok")
# @login_required(roles=MKT_ROLES)
# def page_tiktok():
#     return render_template("marketing/tiktok.html")

# @bp.route("/marketing/fab")
# @login_required(roles=MKT_ROLES)
# def page_fab():
#     return render_template("marketing/fab.html")

# @bp.route("/marketing/planner")
# @login_required(roles=MKT_ROLES)
# def marketing_planner():
#     return render_template("marketing/planner.html", active="marketing")

# @bp.route("/marketing/channels")
# @login_required(roles=QL_ROLES)
# def marketing_channels():
#     return render_template("marketing/channels.html", active="marketing")

# # ===== APIs =====
# @bp.route("/api/fbads/generate_text", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_fb_text():
#     data = request.get_json() or {}
#     product = data.get("product_desc", "")
#     customer = data.get("customer", "")
#     lang = data.get("lang", "Tiếng Việt")
#     brand = (data.get("brand") or "").strip() or "Tiximax Logistics"
#     tone = (data.get("tone") or "Chuyên nghiệp").strip()

#     if not product or not customer:
#         return jsonify({"error": "Thiếu dữ liệu bắt buộc."}), 400

#     user_prompt = f"""
#     Create marketing content using the fixed template below for a Facebook Ads campaign.
#     Language: {lang}
#     Brand: {brand}
#     Tone/Brand voice: {tone}

#     Input:

#     * Product description: {product}
#     * Customer persona: {customer}

#     REQUIREMENTS:

#     * Faithfully reflect the specified brand voice (tone).
#     * Do not invent promotions/prices if none are provided.
#     * Output only ONE complete piece following the template (Analysis → Campaign Idea → Facebook Post → IMAGE\_PROMPT).

#     """.strip()
#     u_prompt, sys_inst = apply_occasion_lock(user_prompt, persona_vi)

#     try:
#         t0 = time.time()
#         text = call_gemini_flash(u_prompt, sys_inst, [])
#         latency = time.time() - t0
#         return jsonify({"text": text, "meta": {"latency_sec": round(latency, 2)}})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo nội dung: {str(e)}"}), 500

# @bp.route("/api/fbads/generate_images", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_fb_imgs():
#     form_data = request.form
#     result_text = form_data.get("result_text", "")
#     product = form_data.get("product_desc", "")
#     customer = form_data.get("customer", "")
#     brand = (form_data.get("brand", "") or "").strip() or "Tiximax Logistics"
#     engine_label = form_data.get("engine_label", "Gemini 2.0 Flash")
#     aspect = (form_data.get("aspect", "1:1") or "1:1").strip()
#     if aspect not in ALLOWED_ASPECTS:
#         aspect = "1:1"
#     style = form_data.get("style_preset", "Semi-realistic")
#     composition = form_data.get("composition", "Lifestyle scene")

#     add_logo = form_data.get("add_logo", "false").lower() == "true"
#     keep_logo = form_data.get("keep_logo_original", "true").lower() == "true"
#     logo_scale = float(form_data.get("logo_scale", 0.15))
#     logo_margin = int(form_data.get("logo_margin", 20))

#     logo_img = None
#     if request.files.get("logo_file"):
#         try:
#             logo_img = Image.open(request.files["logo_file"].stream).convert("RGBA")
#         except Exception:
#             logo_img = None
#     elif add_logo:
#         try:
#             logo_img = load_default_logo(current_app.root_path)
#         except Exception:
#             from PIL import Image as PILImage
#             default_path = os.path.join(current_app.root_path, "static", "images", "logo.png")
#             if os.path.exists(default_path):
#                 try:
#                     logo_img = PILImage.open(default_path).convert("RGBA")
#                 except Exception:
#                     logo_img = None

#     prompt_raw = extract_image_prompt(result_text) if result_text else None
#     if not prompt_raw:
#         subject = f"{brand} – {product} (audience: {customer})"
#         prompt_raw = build_image_prompt(subject=subject, aspect_ratio=aspect, style=style, composition=composition, include_logo=(not add_logo))

#     try:
#         prompt_en = ensure_english_prompt(prompt_raw)
#         engine = "gemini2" if engine_label == "Gemini 2.0 Flash" else "imagen4"
#         images = generate_image_via_gemini_api(prompt_en, engine=engine, aspect_ratio=aspect, n_images=2)
#         images = [conform_aspect(im, aspect, mode="crop", bg="#FFFFFF") for im in (images or [])]

#         if add_logo and images:
#             if logo_img is None:
#                 return jsonify({"error": "Không tìm thấy logo (static/images/logo.png) hoặc file upload."}), 400
#             images = add_logo_to_images(images, logo_img, margin=logo_margin, keep_original=keep_logo, scale=logo_scale)

#         return jsonify({"images": [pil_to_base64(img) for img in images], "used_prompt": prompt_en})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo ảnh: {str(e)}"}), 500

# @bp.route("/api/rephrase", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_rephrase():
#     data = request.get_json() or {}
#     text_src = data.get("text_src", "")
#     lang = data.get("lang", "Tiếng Việt")
#     tone = data.get("tone", "Chuyên nghiệp")
#     if not text_src.strip():
#         return jsonify({"error": "Thiếu văn bản đầu vào."}), 400
#     try:
#         text = generate_rephrase_content(text_src, lang, tone)
#         return jsonify({"text": text})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi viết lại: {str(e)}"}), 500

# @bp.route("/api/tiktok", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_tiktok():
#     data = request.get_json() or {}
#     brief = data.get("brief", "")
#     lang = data.get("lang", "Tiếng Việt")
#     duration = int(data.get("duration", 20))
#     objective = data.get("objective", "Chuyển đổi inbox")
#     if not brief.strip():
#         return jsonify({"error": "Thiếu nội dung kịch bản."}), 400
#     try:
#         text = generate_tiktok_content(brief, lang, duration, objective)
#         return jsonify({"text": text})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo TikTok content: {str(e)}"}), 500

# @bp.route("/api/fab", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_fab():
#     data = request.get_json() or {}
#     benefits = data.get("benefits", "")
#     lang = data.get("lang", "Tiếng Việt")
#     extra = data.get("extra", "")
#     if not benefits.strip():
#         return jsonify({"error": "Thiếu lợi ích sản phẩm/dịch vụ."}), 400
#     try:
#         text = generate_fab_content(benefits, lang, extra)
#         return jsonify({"text": text})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo FAB content: {str(e)}"}), 500

# def _merge_channels_for_planner():
#     try:
#         builtin = list_all_for_planner() or []
#     except Exception:
#         builtin = []
#     try:
#         custom = load_channels() or []
#     except Exception:
#         custom = []
#     seen, merged = set(), []
#     for c in (builtin + custom):
#         key = (c.get('id') or c.get('name') or '').strip().lower()
#         if not key or key in seen:
#             continue
#         if c.get('archived'):
#             continue
#         merged.append(c)
#         seen.add(key)
#     return merged

# @bp.route("/api/channels", methods=["GET"])
# @login_required(roles=MKT_ROLES)
# def api_channels_list():
#     return jsonify({"items": _merge_channels_for_planner()})

# @bp.route("/api/channels/custom", methods=["GET"])
# @login_required(roles=QL_ROLES)
# def api_channels_list_custom():
#     return jsonify({"items": load_channels()})

# @bp.route("/api/channels", methods=["POST"])
# @login_required(roles=QL_ROLES)
# def api_channels_create():
#     d = request.get_json(silent=True) or {}
#     try:
#         item = create_channel(d)
#         return jsonify(item), 201
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# @bp.route("/api/channels/<cid>", methods=["PUT","PATCH"])
# @login_required(roles=QL_ROLES)
# def api_channels_update(cid):
#     d = request.get_json(silent=True) or {}
#     try:
#         item = update_channel(cid, d)
#         return jsonify(item)
#     except KeyError:
#         return jsonify({"error": "Not found"}), 404
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# @bp.route("/api/channels/<cid>", methods=["DELETE"])
# @login_required(roles=QL_ROLES)
# def api_channels_delete(cid):
#     try:
#         delete_channel(cid)
#         return jsonify({"ok": True})
#     except Exception as e:
#         return jsonify({"error": str(e)}), 400

# # @bp.route("/api/channels/prompt", methods=["POST"])
# # @login_required(roles=QL_ROLES)
# # def api_channels_prompt():
# #     d = request.get_json(silent=True) or {}
# #     channel_in = d.get("channel", "")
# #     lang = d.get("lang", "Tiếng Việt")
# #     tones = d.get("tones", [])
# #     channel = _normalize_channel(channel_in)
# #     ch = get_by_name(channel)
# #     desc = _describe_custom_channel(ch, lang) if ch else _describe_builtin_channel(channel, lang)
# #     tones_line = ", ".join(tones) if tones else "Chuyên nghiệp, rõ ràng"
# #     sys_ask = f"""
# #     You are a prompt engineer. Based on the channel specification below,
# #     write a concise, production-ready **SYSTEM PROMPT** (in {lang}) for a content generator agent for **Tiximax Logistics**.
# #     Requirements:
# #     - Start with a 1–2 sentence role definition.
# #     - Then 3–8 bullet rules aligned with the channel and this brand voice: {tones_line}.
# #     - Include a section "ĐẦU RA (markdown)" that defines the exact output structure.
# #     - Do NOT invent pricing/promotions.
# #     - Tailor strictly to the channel constraints.
# #     Channel specification:
# #     {desc}

# #     After the SYSTEM PROMPT, also include a short **USER PROMPT (example)**.
# #     Format:

# #     ### SYSTEM PROMPT
# #     ...
# #     ### USER PROMPT (example)
# #     ...
# #     """.strip()

# #     try:
# #         result = call_gemini_flash_planner(sys_ask, "", [])
# #     except Exception as e:
# #         return jsonify({"error": f"Lỗi gọi Gemini: {e}"}), 500
# #     return jsonify({"channel": channel, "generated": result})

# # # === Planner API ===
# # @bp.route("/api/planner/generate", methods=["POST"])
# # @login_required(api=True, roles=MKT_ROLES)
# # def api_planner_generate():
# #     d = request.get_json(silent=True) or {}
# #     goal       = d.get("goal") or (d.get("objectives") or [None])[0]
# #     channel_in = d.get("channel", "")
# #     channel    = _normalize_channel(channel_in)
# #     tones      = d.get("tones", [])
# #     lang       = d.get("lang", "Tiếng Việt")

# #     system_prompt = _build_system_prompt_ifelse(channel, goal, tones, lang)
# #     up_body = build_user_prompt_body({**d, "channel": channel})
# #     user_prompt, sys_inst = apply_occasion_lock(up_body, system_prompt)

# #     t0 = time.time()
# #     try:
# #         text = call_gemini_flash_planner(user_prompt, sys_inst, [SystemMessage(persona_vi)])
# #     except Exception as e:
# #         try:
# #             app.logger.exception("Planner LLM error: %s", e)
# #         except Exception:
# #             pass
# #         return jsonify({"error": f"Lỗi LLM: {e}"}), 500
# #     dt = time.time() - t0

# #     return jsonify({
# #         "text": text,
# #         "meta": {"latency_sec": round(dt, 2), "channel": channel or "N/A", "goal": goal or "N/A"}
# #     })




# # ===== Đọc channels.json (cache theo mtime) =====
# path_json = "./app/Helpers/Marketing_Planner/channels.json"

# _CH_CACHE = {"items": None, "mtime": 0.0}

# def _load_channels() -> List[dict]:
#     fp = path_json
#     if not fp.exists():
#         return []
#     mtime = fp.stat().st_mtime
#     if _CH_CACHE["items"] is not None and _CH_CACHE["mtime"] == mtime:
#         return _CH_CACHE["items"]  # type: ignore
#     try:
#         data = json.loads(fp.read_text(encoding="utf-8"))
#         if isinstance(data, list):
#             _CH_CACHE["items"] = data
#             _CH_CACHE["mtime"] = mtime
#             return data
#     except Exception as e:
#         current_app.logger.exception("Failed to read channels.json: %s", e)
#     return []

# def _find_channel_by_name(name: str) -> Optional[dict]:
#     key = (name or "").strip().lower()
#     if not key:
#         return None
#     for ch in _load_channels():
#         nm = (ch.get("name") or "").strip().lower()
#         if nm == key:
#             return ch
#     for ch in _load_channels():
#         nm = (ch.get("name") or "").strip().lower()
#         if key in nm:
#             return ch
#     return None

# # ===== Parse độ dài =====
# _LEN_RANGE_RE = re.compile(r"(\d{2,5})\s*[-–—]\s*(\d{2,5})")
# _LEN_ONE_RE   = re.compile(r"(\d{2,5})")

# def _words_range_from_inputs(*, length_input: str, channel: Optional[dict]) -> Tuple[int,int,int,int]:
#     """
#     Trả về (min_words, max_words, target_words, tolerance_pct):
#     - Ưu tiên chuỗi 'length' user nhập (vd: "300-500 từ", "2000 từ")
#     - Nếu rỗng, dùng field 'length' của channel (nếu là số)
#     - Nếu vẫn không có, trả default 120–220 (an toàn)
#     """
#     s = (length_input or "").lower().strip()

#     m = _LEN_RANGE_RE.search(s)
#     if m:
#         lo = max(50, int(m.group(1)))
#         hi = max(lo + 10, int(m.group(2)))
#         target = round((lo + hi) / 2)
#         tol = max(4, min(30, round((hi - target) * 100 / max(1, target))))
#         return lo, hi, target, tol

#     m1 = _LEN_ONE_RE.search(s)
#     if m1:
#         v  = max(50, int(m1.group(1)))
#         lo = max(50, round(v * 0.85))
#         hi = round(v * 1.15)
#         tol = 4 if v <= 300 else 6
#         return lo, hi, v, tol

#     if channel:
#         raw = str(channel.get("length") or "").strip()
#         if raw.isdigit():
#             v  = max(50, int(raw))
#             lo = max(50, round(v * 0.85))
#             hi = round(v * 1.15)
#             tol = 4 if v <= 300 else 6
#             return lo, hi, v, tol

#     return 120, 220, 170, 30

# def _choose_mode(target_words: int) -> str:
#     return "short" if target_words <= 1000 else "long"

# # ===== Prompt builders =====
# def _build_system_instruction(channel: dict, lang: str, tones: List[str]) -> str:
#     def g(k: str) -> str:
#         return str(channel.get(k) or "").strip()

#     out = [
#         "Bạn là trợ lý sáng tạo nội dung **theo kênh** cho thương hiệu.",
#         f"- Ngôn ngữ: {lang or 'Tiếng Việt'}",
#         f"- Kênh: {g('name')}{' ('+g('platform')+')' if g('platform') else ''}"
#     ]
#     if tones: out.append(f"- Giọng điệu ưu tiên: {', '.join(t for t in tones if t).strip()}")
#     if g("audience"):      out.append(f"- Đối tượng: {g('audience')}")
#     if g("content_guide"): out.append(f"- Hướng dẫn nội dung: {g('content_guide')}")
#     if g("visual_guide"):  out.append(f"- Visual guide: {g('visual_guide')}")
#     if g("formats"):       out.append(f"- Formats gợi ý: {g('formats')}")
#     if g("hashtags"):      out.append(f"- Hashtags policy: {g('hashtags')}")
#     if g("cta"):           out.append(f"- CTA gợi ý theo kênh: {g('cta')}")
#     if g("risk_notes"):    out.append(f"- Lưu ý rủi ro: {g('risk_notes')}")
#     if g("special"):       out.append(f"- Lưu ý đặc biệt: {g('special')}")

#     out += [
#         "",
#         "NGUYÊN TẮC BẮT BUỘC:",
#         "- Không in ra các dòng tham số như: Goal:/Stage:/Channel:/Format:/Tone:/Keywords:/CTA:/Language:",
#         "- Không YAML front-matter.",
#         "- Không mục lục (TOC).",
#         "- Viết Markdown hợp lệ, đoạn ngắn, gạch đầu dòng gọn gàng."
#     ]
#     return "\n".join(out).strip()

# def _build_user_prompt(
#     *, goal: str, stage: str, format_name: str, length_line: str,
#     tones: List[str], keywords: str, offer: str, cta: str, lang: str,
#     min_words: int, max_words: int, target_words: int
# ) -> Tuple[str, str]:
#     base = f"""MỤC TIÊU TRUYỀN THÔNG: {goal}
# Giai đoạn hành trình: {stage}
# Định dạng nội dung: {format_name}
# Độ dài yêu cầu: {length_line or f"{min_words}-{max_words} từ"} (đích {target_words} từ, biên {min_words}–{max_words})

# Phong cách ngôn ngữ: {", ".join(tones) if tones else "(mặc định theo kênh)"}
# Từ khóa chiến lược: {keywords or "(không)"} 
# Chương trình ưu đãi: {offer or "(không)"} 
# CTA mong muốn: {cta or "(không)"} 

# YÊU CẦU ĐẦU RA:
# - Bố cục dễ đọc (đoạn ngắn + gạch đầu dòng).
# - Có 1 hook đầu (nếu phù hợp kênh).
# - Nhấn lợi ích người dùng (không chỉ liệt kê tính năng).
# - CTA rõ ràng và phù hợp {format_name}.
# - Tôn trọng “Hashtags policy” của kênh (nếu có).
# """.strip()
#     final = base + "\n\nViết nội dung ngay bây giờ."
#     return base, final

# # ===== Gemini client (fallback offline nếu chưa có key) =====
# _USE_GEMINI = True
# try:
#     import google.generativeai as genai
# except Exception:
#     _USE_GEMINI = False
#     genai = None  # type: ignore

# def _estimate_tokens_for_words(words: int) -> int:
#     return max(256, int(words * 1.6))

# def _safe_extract_text(resp) -> str:
#     try:
#         t = getattr(resp, "text", None)
#         if isinstance(t, str) and t.strip():
#             return t.strip()
#     except Exception:
#         pass
#     try:
#         buf = []
#         for c in getattr(resp, "candidates", []) or []:
#             cont = getattr(c, "content", None)
#             if not cont: continue
#             for p in getattr(cont, "parts", []) or []:
#                 t = getattr(p, "text", None)
#                 if t: buf.append(str(t))
#                 elif isinstance(p, dict) and "text" in p: buf.append(str(p["text"]))
#         return "\n".join(buf).strip()
#     except Exception:
#         return ""

# def _call_gemini_once(*, system_instruction: str, final_prompt: str,
#                       max_output_tokens: int, model_name: str, temperature: float):
#     model = genai.GenerativeModel(model_name=model_name, system_instruction=system_instruction)
#     resp = model.generate_content(
#         final_prompt,
#         generation_config={
#             "max_output_tokens": max_output_tokens,
#             "temperature": float(temperature),
#             "candidate_count": 1
#         },
#         request_options={"timeout": 180}
#     )
#     out = _safe_extract_text(resp)
#     tot = None; frn = None
#     try:
#         tot = getattr(resp, "usage_metadata", None).total_token_count  # type: ignore
#     except Exception:
#         pass
#     try:
#         fr = getattr(resp, "candidates", [None])[0].finish_reason  # type: ignore
#         frmap = {0:"UNSPECIFIED", 1:"STOP", 2:"MAX_TOKENS", 3:"SAFETY", 4:"OTHER"}
#         frn = frmap.get(int(fr), str(fr))
#     except Exception:
#         pass
#     return out, tot, frn

# def _generate_with_gemini(*, system_instruction: str, final_prompt: str,
#                           target_words: int, max_words: int,
#                           model_name: str, temperature: float):
#     tok = min(4096, _estimate_tokens_for_words(max_words) + 128)
#     attempts = [
#         (tok, temperature),
#         (int(tok * 0.85), max(0.1, temperature - 0.1)),
#         (int(tok * 0.80), max(0.1, temperature - 0.2)),
#         (int(tok * 0.75), max(0.1, temperature - 0.3)),
#     ]
#     usage = []
#     text = ""; fr_last = None
#     t0 = time.time()
#     for i, (mx, temp) in enumerate(attempts, 1):
#         out, tot, frn = _call_gemini_once(
#             system_instruction=system_instruction,
#             final_prompt=final_prompt,
#             max_output_tokens=mx,
#             model_name=model_name,
#             temperature=temp
#         )
#         usage.append({"attempt": i, "max_output_tokens": mx, "temperature": temp,
#                       "finish_reason": frn, "usage_total": tot})
#         if out.strip():
#             text = out.strip(); fr_last = frn; break
#         fr_last = frn
#     return text, {"usage_attempts": usage, "latency_sec": round(time.time()-t0, 2), "finish_reason": fr_last}

# def _generate_offline_stub(*, channel: dict, goal: str, stage: str, format_name: str,
#                            min_words: int, max_words: int, target_words: int,
#                            tones: List[str], keywords: str, offer: str, cta: str, lang: str) -> str:
#     tone_line = ", ".join(tones) if tones else "theo kênh"
#     return f"""**[DEMO OFFLINE] {channel.get('name','(Kênh)')} — {format_name}**

# *Goal:* {goal} | *Stage:* {stage} | *Lang:* {lang}
# *Tones:* {tone_line}
# *Length target:* ~{target_words} từ (min {min_words} / max {max_words})

# Nội dung demo (offline). Hãy cấu hình `GEMINI_API_KEY` để sinh bản chính thức.
# - Keywords: {keywords or '(none)'}
# - Offer: {offer or '(none)'}
# - CTA: **{cta or '(none)'}**

# • Dòng 1: Hook ngắn gọn, gợi mở lợi ích.  
# • Dòng 2–3: Vấn đề người dùng và giải pháp của bạn.  
# • Dòng 4: Điểm khác biệt chính.  
# • Dòng 5: CTA.
# """

# # ==========================
# #  ROUTES
# # ==========================

# @bp.route.get("/channels")
# @login_required(roles=MKT_ROLES)
# def channels_list():
#     return jsonify({"items": _load_channels()})

# @bp.route.post("/planner/generate")
# @login_required(api=True, roles=MKT_ROLES)
# def planner_generate():
#     d: Dict[str, Any] = request.get_json(silent=True) or {}

#     channel_name = (d.get("channel") or "").strip()
#     goal         = (d.get("goal") or "").strip()
#     stage        = (d.get("stage") or "").strip()
#     format_name  = (d.get("format") or d.get("format_name") or "").strip()
#     length_line  = (d.get("length") or "").strip()
#     tones        = d.get("tones") or []
#     if isinstance(tones, str):
#         tones = [t.strip() for t in tones.split(",") if t.strip()]
#     keywords     = (d.get("keywords") or "").strip()
#     offer        = (d.get("offer") or "").strip()
#     cta          = (d.get("cta") or "").strip()
#     lang         = (d.get("lang") or "Tiếng Việt").strip()

#     # Client có thể gửi sẵn các range
#     desired_min  = d.get("desired_min_words")
#     desired_max  = d.get("desired_max_words")
#     target_words = d.get("target_words")
#     tolerance    = d.get("tolerance_pct")
#     mode         = (d.get("mode") or "").strip()
#     fast         = bool(d.get("fast", False))

#     ch = _find_channel_by_name(channel_name)
#     if not ch:
#         return jsonify({"error": f"Channel '{channel_name}' not found in channels.json"}), 404

#     if all(isinstance(x, int) for x in [desired_min, desired_max, target_words, tolerance]):
#         min_words, max_words, tgt, tol = int(desired_min), int(desired_max), int(target_words), int(tolerance)
#     else:
#         min_words, max_words, tgt, tol = _words_range_from_inputs(length_input=length_line, channel=ch)

#     if not mode:
#         mode = _choose_mode(tgt)

#     sys_inst = _build_system_instruction(ch, lang, tones)
#     base_up, final_up = _build_user_prompt(
#         goal=goal, stage=stage, format_name=format_name, length_line=length_line,
#         tones=tones, keywords=keywords, offer=offer, cta=cta, lang=lang,
#         min_words=min_words, max_words=max_words, target_words=tgt
#     )

#     model_name  = os.getenv("PLANNER_MODEL", os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash"))
#     temperature = float(os.getenv("PLANNER_TEMPERATURE", os.getenv("GEMINI_TEMPERATURE", "0.6")))
#     api_key     = (os.getenv("GEMINI_API_KEY") or "").strip()

#     text_out = ""; usage_meta = {}; used_model = model_name
#     if _USE_GEMINI and api_key:
#         try:
#             genai.configure(api_key=api_key)
#             text_out, usage_meta = _generate_with_gemini(
#                 system_instruction=sys_inst,
#                 final_prompt=final_up,
#                 target_words=tgt,
#                 max_words=max_words,
#                 model_name=model_name,
#                 temperature=temperature
#             )
#         except Exception as e:
#             current_app.logger.exception("Gemini error: %s", e)
#             usage_meta = {"error": str(e)}
#             text_out = ""
#     else:
#         text_out = _generate_offline_stub(
#             channel=ch, goal=goal, stage=stage, format_name=format_name,
#             min_words=min_words, max_words=max_words, target_words=tgt,
#             tones=tones, keywords=keywords, offer=offer, cta=cta, lang=lang
#         )

#     if not (text_out or "").strip():
#         text_out = "*(Không tạo được nội dung.)*"

#     meta = {
#         "mode": mode, "fast": fast,
#         "channel": ch.get("name"), "platform": ch.get("platform"),
#         "min_words": min_words, "max_words": max_words,
#         "target_words": tgt, "tolerance_pct": tol,
#         "model": used_model, "temperature": temperature,
#         **usage_meta
#     }
#     debug = {
#         "system_instruction": sys_inst,
#         "base_user_prompt": base_up,
#         "final_user_prompt": final_up
#     }
#     return jsonify({"text": text_out, "meta": meta, "debug": debug})


# src/app/routes/marketing.py
# from __future__ import annotations

# import os
# import time
# import re
# import json
# from pathlib import Path
# from typing import Any, Dict, List, Optional, Tuple

# from flask import Blueprint, render_template, jsonify, request, current_app
# from flask import current_app as app

# from app.Login.login_required import login_required
# from app.Helpers.prompt_KT import persona_vi
# from app.Helpers.LLM_client import (
#     apply_occasion_lock,
#     call_gemini_flash,
#     call_gemini_flash_planner,
#     extract_image_prompt,
#     ensure_english_prompt,
# )
# from app.Helpers.Image_generation_and_processing import (
#     build_image_prompt,
#     generate_image_via_gemini_api,
#     add_logo_to_images,
#     pil_to_base64,
#     load_default_logo,
#     conform_aspect,
#     ALLOWED_ASPECTS,
# )
# from app.Helpers.Content_generation import (
#     generate_rephrase_content,
#     generate_tiktok_content,
#     generate_fab_content,
# )

# # (Các module Marketing_Planner cũ của bạn vẫn giữ nguyên để dùng chỗ khác)
# from PIL import Image

# # ====================================
# # Blueprint
# # ====================================
# bp = Blueprint("marketing", __name__)

# # ====================================
# # Roles
# # ====================================
# MKT_ROLES = ["marketing", "sales", "manager_marketing", "manager_sales"]
# QL_ROLES = ["admin", "manager_marketing", "manager_sales"]

# # ====================================
# # Pages
# # ====================================
# @bp.route("/marketing/rephrase")
# @login_required(roles=MKT_ROLES)
# def page_rephrase():
#     return render_template("marketing/rephrase.html")


# @bp.route("/marketing/tiktok")
# @login_required(roles=MKT_ROLES)
# def page_tiktok():
#     return render_template("marketing/tiktok.html")


# @bp.route("/marketing/fab")
# @login_required(roles=MKT_ROLES)
# def page_fab():
#     return render_template("marketing/fab.html")


# @bp.route("/marketing/planner")
# @login_required(roles=MKT_ROLES)
# def marketing_planner():
#     return render_template("marketing/planner.html", active="marketing")


# @bp.route("/marketing/channels")
# @login_required(roles=QL_ROLES)
# def marketing_channels():
#     return render_template("marketing/channels.html", active="marketing")


# # ====================================
# # APIs cũ
# # ====================================
# @bp.route("/api/fbads/generate_text", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_fb_text():
#     data = request.get_json() or {}
#     product = data.get("product_desc", "")
#     customer = data.get("customer", "")
#     lang = data.get("lang", "Tiếng Việt")
#     brand = (data.get("brand") or "").strip() or "Tiximax Logistics"
#     tone = (data.get("tone") or "Chuyên nghiệp").strip()

#     if not product or not customer:
#         return jsonify({"error": "Thiếu dữ liệu bắt buộc."}), 400

#     user_prompt = f"""
# Create marketing content using the fixed template below for a Facebook Ads campaign.
# Language: {lang}
# Brand: {brand}
# Tone/Brand voice: {tone}

# Input:
# * Product description: {product}
# * Customer persona: {customer}

# REQUIREMENTS:
# * Faithfully reflect the specified brand voice (tone).
# * Do not invent promotions/prices if none are provided.
# * Output only ONE complete piece following the template (Analysis → Campaign Idea → Facebook Post → IMAGE_PROMPT).
# """.strip()
#     u_prompt, sys_inst = apply_occasion_lock(user_prompt, persona_vi)

#     try:
#         t0 = time.time()
#         text = call_gemini_flash(u_prompt, sys_inst, [])
#         latency = time.time() - t0
#         return jsonify({"text": text, "meta": {"latency_sec": round(latency, 2)}})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo nội dung: {str(e)}"}), 500


# @bp.route("/api/fbads/generate_images", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_fb_imgs():
#     form_data = request.form
#     result_text = form_data.get("result_text", "")
#     product = form_data.get("product_desc", "")
#     customer = form_data.get("customer", "")
#     brand = (form_data.get("brand", "") or "").strip() or "Tiximax Logistics"
#     engine_label = form_data.get("engine_label", "Gemini 2.0 Flash")
#     aspect = (form_data.get("aspect", "1:1") or "1:1").strip()
#     if aspect not in ALLOWED_ASPECTS:
#         aspect = "1:1"
#     style = form_data.get("style_preset", "Semi-realistic")
#     composition = form_data.get("composition", "Lifestyle scene")

#     add_logo = form_data.get("add_logo", "false").lower() == "true"
#     keep_logo = form_data.get("keep_logo_original", "true").lower() == "true"
#     logo_scale = float(form_data.get("logo_scale", 0.15))
#     logo_margin = int(form_data.get("logo_margin", 20))

#     logo_img = None
#     if request.files.get("logo_file"):
#         try:
#             logo_img = Image.open(request.files["logo_file"].stream).convert("RGBA")
#         except Exception:
#             logo_img = None
#     elif add_logo:
#         try:
#             logo_img = load_default_logo(current_app.root_path)
#         except Exception:
#             from PIL import Image as PILImage
#             default_path = os.path.join(current_app.root_path, "static", "images", "logo.png")
#             if os.path.exists(default_path):
#                 try:
#                     logo_img = PILImage.open(default_path).convert("RGBA")
#                 except Exception:
#                     logo_img = None

#     prompt_raw = extract_image_prompt(result_text) if result_text else None
#     if not prompt_raw:
#         subject = f"{brand} – {product} (audience: {customer})"
#         prompt_raw = build_image_prompt(
#             subject=subject,
#             aspect_ratio=aspect,
#             style=style,
#             composition=composition,
#             include_logo=(not add_logo),
#         )

#     try:
#         prompt_en = ensure_english_prompt(prompt_raw)
#         engine = "gemini2" if engine_label == "Gemini 2.0 Flash" else "imagen4"
#         images = generate_image_via_gemini_api(prompt_en, engine=engine, aspect_ratio=aspect, n_images=2)
#         images = [conform_aspect(im, aspect, mode="crop", bg="#FFFFFF") for im in (images or [])]

#         if add_logo and images:
#             if logo_img is None:
#                 return jsonify({"error": "Không tìm thấy logo (static/images/logo.png) hoặc file upload."}), 400
#             images = add_logo_to_images(
#                 images, logo_img, margin=logo_margin, keep_original=keep_logo, scale=logo_scale
#             )

#         return jsonify({"images": [pil_to_base64(img) for img in images], "used_prompt": prompt_en})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo ảnh: {str(e)}"}), 500


# @bp.route("/api/rephrase", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_rephrase():
#     data = request.get_json() or {}
#     text_src = data.get("text_src", "")
#     lang = data.get("lang", "Tiếng Việt")
#     tone = data.get("tone", "Chuyên nghiệp")
#     if not text_src.strip():
#         return jsonify({"error": "Thiếu văn bản đầu vào."}), 400
#     try:
#         text = generate_rephrase_content(text_src, lang, tone)
#         return jsonify({"text": text})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi viết lại: {str(e)}"}), 500


# @bp.route("/api/tiktok", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_tiktok():
#     data = request.get_json() or {}
#     brief = data.get("brief", "")
#     lang = data.get("lang", "Tiếng Việt")
#     duration = int(data.get("duration", 20))
#     objective = data.get("objective", "Chuyển đổi inbox")
#     if not brief.strip():
#         return jsonify({"error": "Thiếu nội dung kịch bản."}), 400
#     try:
#         text = generate_tiktok_content(brief, lang, duration, objective)
#         return jsonify({"text": text})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo TikTok content: {str(e)}"}), 500


# @bp.route("/api/fab", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_fab():
#     data = request.get_json() or {}
#     benefits = data.get("benefits", "")
#     lang = data.get("lang", "Tiếng Việt")
#     extra = data.get("extra", "")
#     if not benefits.strip():
#         return jsonify({"error": "Thiếu lợi ích sản phẩm/dịch vụ."}), 400
#     try:
#         text = generate_fab_content(benefits, lang, extra)
#         return jsonify({"text": text})
#     except Exception as e:
#         return jsonify({"error": f"Lỗi khi tạo FAB content: {str(e)}"}), 500


# # ====================================
# # Planner + Channels (mới)
# # ====================================

# def _resolve_channels_path() -> Path:
#     here = Path(__file__).resolve()
#     candidates = [
#         # chạy layout chuẩn: src/app/routes/marketing.py -> src/app/Data_app/channels.json
#         here.parent.parent / "Data_app" / "channels.json",

#         # theo yêu cầu của bạn: app/Data_app/channels.json (CWD là project root)
#         Path.cwd() / "app" / "Data_app" / "channels.json",

#         # một số dự án chạy CWD=project root nhưng có thư mục src/
#         Path.cwd() / "src" / "app" / "Data_app" / "channels.json",
#     ]
#     for p in candidates:
#         if p.exists():
#             return p
#     # fallback: ưu tiên đúng yêu cầu
#     return Path.cwd() / "app" / "Data_app" / "channels.json"

# _CHANNELS_PATH = _resolve_channels_path()
# _CHANNELS_CACHE = {"items": None, "mtime": 0.0}

# def _load_channels() -> list[dict]:
#     p = _CHANNELS_PATH
#     try:
#         # cache theo mtime
#         if p.exists():
#             mtime = p.stat().st_mtime
#             if _CHANNELS_CACHE["items"] is not None and _CHANNELS_CACHE["mtime"] == mtime:
#                 return _CHANNELS_CACHE["items"]  # type: ignore
#             data = json.loads(p.read_text(encoding="utf-8"))
#             if isinstance(data, list):
#                 _CHANNELS_CACHE["items"] = data
#                 _CHANNELS_CACHE["mtime"] = mtime
#                 return data
#     except Exception as e:
#         try:
#             current_app.logger.exception("Failed to read channels.json at %s: %s", p, e)
#         except Exception:
#             print(f"[channels] read error at {p}: {e}")
#     return []


# def _find_channel_by_name(name: str) -> Optional[dict]:
#     key = (name or "").strip().lower()
#     if not key:
#         return None
#     for ch in _load_channels():
#         nm = (ch.get("name") or "").strip().lower()
#         if nm == key:
#             return ch
#     for ch in _load_channels():
#         nm = (ch.get("name") or "").strip().lower()
#         if key in nm:
#             return ch
#     return None


# # Parse độ dài
# _LEN_RANGE_RE = re.compile(r"(\d{2,5})\s*[-–—]\s*(\d{2,5})")
# _LEN_ONE_RE = re.compile(r"(\d{2,5})")


# def _words_range_from_inputs(*, length_input: str, channel: Optional[dict]) -> Tuple[int, int, int, int]:
#     """
#     Trả về (min_words, max_words, target_words, tolerance_pct):
#     - Ưu tiên chuỗi 'length' user nhập (vd: "300-500 từ", "2000 từ")
#     - Nếu rỗng, dùng field 'length' của channel (nếu là số)
#     - Nếu vẫn không có, trả default 120–220 (an toàn)
#     """
#     s = (length_input or "").lower().strip()

#     m = _LEN_RANGE_RE.search(s)
#     if m:
#         lo = max(50, int(m.group(1)))
#         hi = max(lo + 10, int(m.group(2)))
#         target = round((lo + hi) / 2)
#         tol = max(4, min(30, round((hi - target) * 100 / max(1, target))))
#         return lo, hi, target, tol

#     m1 = _LEN_ONE_RE.search(s)
#     if m1:
#         v = max(50, int(m1.group(1)))
#         lo = max(50, round(v * 0.85))
#         hi = round(v * 1.15)
#         tol = 4 if v <= 300 else 6
#         return lo, hi, v, tol

#     if channel:
#         raw = str(channel.get("length") or "").strip()
#         if raw.isdigit():
#             v = max(50, int(raw))
#             lo = max(50, round(v * 0.85))
#             hi = round(v * 1.15)
#             tol = 4 if v <= 300 else 6
#             return lo, hi, v, tol

#     return 120, 220, 170, 30


# def _choose_mode(target_words: int) -> str:
#     return "short" if target_words <= 1000 else "long"


# def _build_system_instruction(channel: dict, lang: str, tones: List[str]) -> str:
#     def g(k: str) -> str:
#         return str(channel.get(k) or "").strip()

#     out = [
#         "Bạn là trợ lý sáng tạo nội dung **theo kênh** cho thương hiệu.",
#         f"- Ngôn ngữ: {lang or 'Tiếng Việt'}",
#         f"- Kênh: {g('name')}{' ('+g('platform')+')' if g('platform') else ''}",
#     ]
#     if tones:
#         out.append(f"- Giọng điệu ưu tiên: {', '.join(t for t in tones if t).strip()}")
#     if g("audience"):
#         out.append(f"- Đối tượng: {g('audience')}")
#     if g("content_guide"):
#         out.append(f"- Hướng dẫn nội dung: {g('content_guide')}")
#     if g("visual_guide"):
#         out.append(f"- Visual guide: {g('visual_guide')}")
#     if g("formats"):
#         out.append(f"- Formats gợi ý: {g('formats')}")
#     if g("hashtags"):
#         out.append(f"- Hashtags policy: {g('hashtags')}")
#     if g("cta"):
#         out.append(f"- CTA gợi ý theo kênh: {g('cta')}")
#     if g("risk_notes"):
#         out.append(f"- Lưu ý rủi ro: {g('risk_notes')}")
#     if g("special"):
#         out.append(f"- Lưu ý đặc biệt: {g('special')}")

#     out += [
#         "",
#         "NGUYÊN TẮC BẮT BUỘC:",
#         "- Không in ra các dòng tham số như: Goal:/Stage:/Channel:/Format:/Tone:/Keywords:/CTA:/Language:",
#         "- Không YAML front-matter.",
#         "- Không mục lục (TOC).",
#         "- Viết Markdown hợp lệ, đoạn ngắn, gạch đầu dòng gọn gàng.",
#     ]
#     return "\n".join(out).strip()


# def _build_user_prompt(
#     *,
#     goal: str,
#     stage: str,
#     format_name: str,
#     length_line: str,
#     tones: List[str],
#     keywords: str,
#     offer: str,
#     cta: str,
#     lang: str,
#     min_words: int,
#     max_words: int,
#     target_words: int,
# ) -> Tuple[str, str]:
#     base = f"""MỤC TIÊU TRUYỀN THÔNG: {goal}
# Giai đoạn hành trình: {stage}
# Định dạng nội dung: {format_name}
# Độ dài yêu cầu: {length_line or f"{min_words}-{max_words} từ"} (đích {target_words} từ, biên {min_words}–{max_words})

# Phong cách ngôn ngữ: {", ".join(tones) if tones else "(mặc định theo kênh)"}
# Từ khóa chiến lược: {keywords or "(không)"} 
# Chương trình ưu đãi: {offer or "(không)"} 
# CTA mong muốn: {cta or "(không)"} 

# YÊU CẦU ĐẦU RA:
# - Bố cục dễ đọc (đoạn ngắn + gạch đầu dòng).
# - Có 1 hook đầu (nếu phù hợp kênh).
# - Nhấn lợi ích người dùng (không chỉ liệt kê tính năng).
# - CTA rõ ràng và phù hợp {format_name}.
# - Tôn trọng “Hashtags policy” của kênh (nếu có).
# """.strip()
#     final = base + "\n\nViết nội dung ngay bây giờ."
#     return base, final


# # Gemini (tùy chọn)
# _USE_GEMINI = True
# try:
#     import google.generativeai as genai
# except Exception:
#     _USE_GEMINI = False
#     genai = None  # type: ignore


# def _estimate_tokens_for_words(words: int) -> int:
#     return max(256, int(words * 1.6))


# def _safe_extract_text(resp) -> str:
#     # 1) phản xạ nhanh
#     try:
#         t = getattr(resp, "text", None)
#         if isinstance(t, str) and t.strip():
#             return t.strip()
#     except Exception:
#         pass
#     # 2) bóc parts
#     try:
#         buf: List[str] = []
#         for c in getattr(resp, "candidates", []) or []:
#             cont = getattr(c, "content", None)
#             if not cont:
#                 continue
#             for p in getattr(cont, "parts", []) or []:
#                 t = getattr(p, "text", None)
#                 if t:
#                     buf.append(str(t))
#                 elif isinstance(p, dict) and "text" in p:
#                     buf.append(str(p["text"]))
#         return "\n".join(buf).strip()
#     except Exception:
#         return ""


# def _call_gemini_once(
#     *,
#     system_instruction: str,
#     final_prompt: str,
#     max_output_tokens: int,
#     model_name: str,
#     temperature: float,
# ) -> Tuple[str, Optional[int], Optional[str]]:
#     model = genai.GenerativeModel(model_name=model_name, system_instruction=system_instruction)
#     resp = model.generate_content(
#         final_prompt,
#         generation_config={
#             "max_output_tokens": max_output_tokens,
#             "temperature": float(temperature),
#             "candidate_count": 1,
#         },
#         request_options={"timeout": 180},
#     )
#     out = _safe_extract_text(resp)
#     tot = None
#     frn = None
#     try:
#         tot = getattr(resp, "usage_metadata", None).total_token_count  # type: ignore
#     except Exception:
#         pass
#     try:
#         fr = getattr(resp, "candidates", [None])[0].finish_reason  # type: ignore
#         frmap = {0: "UNSPECIFIED", 1: "STOP", 2: "MAX_TOKENS", 3: "SAFETY", 4: "OTHER"}
#         frn = frmap.get(int(fr), str(fr))
#     except Exception:
#         pass
#     return out, tot, frn


# def _generate_with_gemini(
#     *,
#     system_instruction: str,
#     final_prompt: str,
#     target_words: int,
#     max_words: int,
#     model_name: str,
#     temperature: float,
# ) -> Tuple[str, Dict[str, Any]]:
#     tok = min(4096, _estimate_tokens_for_words(max_words) + 128)
#     attempts = [
#         (tok, temperature),
#         (int(tok * 0.85), max(0.1, temperature - 0.1)),
#         (int(tok * 0.80), max(0.1, temperature - 0.2)),
#         (int(tok * 0.75), max(0.1, temperature - 0.3)),
#     ]
#     usage_hist = []
#     text = ""
#     fr_last = None
#     t0 = time.time()
#     for i, (mx, temp) in enumerate(attempts, 1):
#         out, tot, frn = _call_gemini_once(
#             system_instruction=system_instruction,
#             final_prompt=final_prompt,
#             max_output_tokens=mx,
#             model_name=model_name,
#             temperature=temp,
#         )
#         usage_hist.append(
#             {
#                 "attempt": i,
#                 "max_output_tokens": mx,
#                 "temperature": temp,
#                 "finish_reason": frn,
#                 "usage_total": tot,
#             }
#         )
#         if out.strip():
#             text = out.strip()
#             fr_last = frn
#             break
#         fr_last = frn

#     latency = round(time.time() - t0, 2)
#     return text, {"usage_attempts": usage_hist, "latency_sec": latency, "finish_reason": fr_last}


# def _generate_offline_stub(
#     *,
#     channel: dict,
#     goal: str,
#     stage: str,
#     format_name: str,
#     min_words: int,
#     max_words: int,
#     target_words: int,
#     tones: List[str],
#     keywords: str,
#     offer: str,
#     cta: str,
#     lang: str,
# ) -> str:
#     tone_line = ", ".join(tones) if tones else "theo kênh"
#     return f"""**[DEMO OFFLINE] {channel.get('name','(Kênh)')} — {format_name}**

# *Goal:* {goal} | *Stage:* {stage} | *Lang:* {lang}
# *Tones:* {tone_line}
# *Length target:* ~{target_words} từ (min {min_words} / max {max_words})

# Nội dung demo (offline). Hãy cấu hình `GEMINI_API_KEY` để sinh bản chính thức.
# - Keywords: {keywords or '(none)'}
# - Offer: {offer or '(none)'}
# - CTA: **{cta or '(none)'}**

# • Dòng 1: Hook ngắn gọn, gợi mở lợi ích.  
# • Dòng 2–3: Vấn đề người dùng và giải pháp của bạn.  
# • Dòng 4: Điểm khác biệt chính.  
# • Dòng 5: CTA.
# """


# # ==========================
# #  Channels Endpoints (alias)
# # ==========================
# @bp.route("/api/channels", methods=["GET"])
# @bp.route("/marketing/api/channels", methods=["GET"])
# @login_required(roles=MKT_ROLES)
# def api_channels_list():
#     return jsonify({"items": _load_channels()})


# # ==========================
# #  Planner Endpoint (alias)
# # ==========================
# @bp.route("/api/planner/generate", methods=["POST"])
# @bp.route("/api/planner/generate/", methods=["POST"])
# @bp.route("/marketing/api/planner/generate", methods=["POST"])
# @bp.route("/marketing/api/planner/generate/", methods=["POST"])
# @login_required(api=True, roles=MKT_ROLES)
# def api_planner_generate():
#     d: Dict[str, Any] = request.get_json(silent=True) or {}

#     channel_name = (d.get("channel") or "").strip()
#     goal = (d.get("goal") or "").strip()
#     stage = (d.get("stage") or "").strip()
#     format_name = (d.get("format") or d.get("format_name") or "").strip()
#     length_line = (d.get("length") or "").strip()
#     tones = d.get("tones") or []
#     if isinstance(tones, str):
#         tones = [t.strip() for t in tones.split(",") if t.strip()]
#     keywords = (d.get("keywords") or "").strip()
#     offer = (d.get("offer") or "").strip()
#     cta = (d.get("cta") or "").strip()
#     lang = (d.get("lang") or "Tiếng Việt").strip()

#     desired_min = d.get("desired_min_words")
#     desired_max = d.get("desired_max_words")
#     target_words = d.get("target_words")
#     tolerance = d.get("tolerance_pct")
#     mode = (d.get("mode") or "").strip()
#     fast = bool(d.get("fast", False))

#     ch = _find_channel_by_name(channel_name)
#     if not ch:
#         return jsonify({"error": f"Channel '{channel_name}' not found in channels.json"}), 404

#     if all(isinstance(x, int) for x in [desired_min, desired_max, target_words, tolerance]):
#         min_words, max_words, tgt, tol = int(desired_min), int(desired_max), int(target_words), int(tolerance)
#     else:
#         min_words, max_words, tgt, tol = _words_range_from_inputs(length_input=length_line, channel=ch)

#     if not mode:
#         mode = _choose_mode(tgt)

#     sys_inst = _build_system_instruction(ch, lang, tones)
#     base_up, final_up = _build_user_prompt(
#         goal=goal,
#         stage=stage,
#         format_name=format_name,
#         length_line=length_line,
#         tones=tones,
#         keywords=keywords,
#         offer=offer,
#         cta=cta,
#         lang=lang,
#         min_words=min_words,
#         max_words=max_words,
#         target_words=tgt,
#     )

#     model_name = os.getenv("PLANNER_MODEL", os.getenv("GEMINI_TEXT_MODEL", "gemini-2.0-flash"))
#     temperature = float(os.getenv("PLANNER_TEMPERATURE", os.getenv("GEMINI_TEMPERATURE", "0.6")))
#     api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

#     text_out = ""
#     usage_meta: Dict[str, Any] = {}
#     used_model = model_name

#     if _USE_GEMINI and api_key:
#         try:
#             genai.configure(api_key=api_key)
#             text_out, usage_meta = _generate_with_gemini(
#                 system_instruction=sys_inst,
#                 final_prompt=final_up,
#                 target_words=tgt,
#                 max_words=max_words,
#                 model_name=model_name,
#                 temperature=temperature,
#             )
#         except Exception as e:
#             current_app.logger.exception("Gemini error: %s", e)
#             usage_meta = {"error": str(e)}
#             text_out = ""
#     else:
#         text_out = _generate_offline_stub(
#             channel=ch,
#             goal=goal,
#             stage=stage,
#             format_name=format_name,
#             min_words=min_words,
#             max_words=max_words,
#             target_words=tgt,
#             tones=tones,
#             keywords=keywords,
#             offer=offer,
#             cta=cta,
#             lang=lang,
#         )

#     if not (text_out or "").strip():
#         text_out = "*(Không tạo được nội dung.)*"

#     meta = {
#         "mode": mode,
#         "fast": fast,
#         "channel": ch.get("name"),
#         "platform": ch.get("platform"),
#         "min_words": min_words,
#         "max_words": max_words,
#         "target_words": tgt,
#         "tolerance_pct": tol,
#         "model": used_model,
#         "temperature": temperature,
#         **usage_meta,
#     }
#     debug = {
#         "system_instruction": sys_inst,
#         "base_user_prompt": base_up,
#         "final_user_prompt": final_up,
#     }
#     return jsonify({"text": text_out, "meta": meta, "debug": debug})




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
