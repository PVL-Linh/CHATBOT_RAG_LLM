import os, json, time, csv
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from PIL import Image

from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
import requests

# LangChain / LLM helpers (giữ nguyên import của bạn)
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.messages import SystemMessage

# Import helper modules (giữ nguyên theo cấu trúc dự án của bạn)
from Helpers.Data_storage import save_item, delete_item, get_items
from Helpers.LLM_client import apply_occasion_lock, call_gemini_flash, extract_image_prompt, ensure_english_prompt
from Helpers.prompt_KT import persona_vi
from Helpers.Image_generation_and_processing import (
    build_image_prompt, generate_image_via_gemini_api,
    add_logo_to_images, pil_to_base64, load_default_logo,
    conform_aspect, ALLOWED_ASPECTS
)
from Helpers.Content_generation import (
    generate_facebook_ads_content, generate_rephrase_content,
    generate_tiktok_content, generate_fab_content
)
from Helpers.prompt_internal import SYSTEM_PRIMER
from Login.login_required import load_users, login_required
# from Login.Logging_config import _log_message_to_csv  # <-- KHÔNG dùng nữa, ta ghi CSV ngay tại app.py
from Helpers.Marketing_Planner.Content_Planner import (
    _normalize_channel, _build_system_prompt_ifelse, build_user_prompt_body
)

try:
    from .Model_LLM.hybrid_retriever import rerank, TOP_K  # khi chạy -m src.app
except ImportError:
    from Model_LLM.hybrid_retriever import rerank, TOP_K

# =====================================
# Flask setup
# =====================================
app = Flask(__name__)
app.config.from_object('config.Config')  # SECRET_KEY etc.
app.config.setdefault('SEND_FILE_MAX_AGE_DEFAULT', 31536000)

try:
    from flask_compress import Compress
    Compress(app)
except Exception:
    pass

# =====================================
# Auth config
# =====================================
# load_users()
# login_required()

# =====================================
# Gemini types
# =====================================
from google.genai import types as genai_types
from dotenv import load_dotenv
load_dotenv()

# =====================================
# Constants & Settings
# =====================================
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "50"))
CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

# =====================================
# CSV logging (WITH session_id)
# =====================================
from zoneinfo import ZoneInfo

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _log_message_to_csv_sid(username: str, role: str, content: str, ts_utc_iso: str, session_id: str = ""):
    """
    Ghi 1 dòng vào CSV theo schema:
    ts_utc, ts_local, username, session_id, role, content
    """
    if not username:
        return
    _ensure_dir(CHAT_LOGS_DIR)
    filepath = os.path.join(CHAT_LOGS_DIR, f"{username}.csv")

    try:
        local_tz = ZoneInfo(LOCAL_TZ_NAME)
    except Exception:
        local_tz = timezone.utc

    try:
        ts_utc = datetime.fromisoformat(ts_utc_iso.replace('Z', '+00:00'))
    except Exception:
        ts_utc = datetime.now(timezone.utc)
        ts_utc_iso = ts_utc.isoformat()

    ts_local_iso = ts_utc.astimezone(local_tz).isoformat()

    file_exists = os.path.exists(filepath)
    with open(filepath, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['ts_utc', 'ts_local', 'username', 'session_id', 'role', 'content'])
        writer.writerow([ts_utc_iso, ts_local_iso, username, session_id or "", role, content])

# =====================================
# Session helpers
# =====================================
def get_history():
    msgs = session.get("messages") or []
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
        session["messages"] = msgs
    return msgs

def add_message(role, content, session_id: str = ""):
    msgs = get_history()
    ts_utc_iso = datetime.now(timezone.utc).isoformat()
    msgs.append({"role": role, "content": content, "ts": ts_utc_iso, "session_id": session_id or ""})
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
    session["messages"] = msgs

    try:
        _log_message_to_csv_sid(session.get('user'), role, content, ts_utc_iso, session_id or "")
    except Exception as e:
        app.logger.exception("Failed to write chat CSV: %s", e)

# =====================================
# Error handlers
# =====================================
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"ok": False, "error": "Not found"}), 404
    try:
        return render_template('home/404.html'), 404
    except Exception:
        return "<h1>404 Not Found</h1>", 404

# =====================================
# Auth routes
# =====================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get('user'):
            return redirect(url_for('chat'))
        next_url = request.args.get("next", "")
        return render_template("home/login.html", next_url=next_url)

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    remember = request.form.get("remember") == "on"

    global USERS
    USERS = load_users()
    user = USERS.get(username)

    if not user or not password or not check_password_hash(user["password_hash"], password):
        return render_template(
            "home/login.html",
            error="Tên đăng nhập hoặc mật khẩu không đúng.",
            next_url=request.form.get("next","")
        )

    session.clear()
    session.permanent = remember
    session['user'] = username
    session['role'] = user.get('role', 'marketing')
    session['messages'] = []  # sẽ hydrate bằng API /frontend nếu cần

    next_url = request.form.get("next") or request.args.get("next") or url_for("chat")
    return redirect(next_url)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =====================================
# Pages (protected)
# =====================================
@app.route('/', methods=['GET'])
@login_required
def chat():
    return render_template(
        'home/chat.html',
        messages=get_history()[-30:],
        current_user=session.get('user'),
        active='chat'
    )

@app.route('/marketing', methods=['GET'])
@login_required(roles=['marketing'])
def marketing():
    return render_template('home/marketing.html', current_user=session.get('user'), active='marketing')

@app.route('/sales', methods=['GET'])
@login_required
def sales():
    return render_template('home/sales.html', current_user=session.get('user'), active='sales')

@app.route('/hr', methods=['GET'])
@login_required
def hr():
    return render_template('home/hr.html', current_user=session.get('user'), active='hr')

@app.route('/guide', methods=['GET'])
@login_required
def guide():
    return render_template('home/guide.html', current_user=session.get('user'), active='guide')

@app.route('/admin', methods=['GET'])
@login_required(roles=['admin'])
def admin():
    return render_template('home/admin.html', current_user=session.get('user'), active='admin')

# =====================================
# Utils: convert history to Gemini format (no system role)
# =====================================
def _to_gemini_history_no_system(history_msgs):
    """
    [{'role','content'}] -> contents cho Gemini 2.x (không dùng role 'system')
    """
    out = []
    for m in history_msgs:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            role = "model"
        else:
            role = "user"
        out.append({"role": role, "parts": [{"text": content}]})
    return out

# =====================================
# Chat API (protected)
# =====================================
from Model_LLM.model_llm import LLM_model

@app.route('/api/chat', methods=['POST'])
@login_required(api=True)
def chat_api():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()

    data = request.get_json(force=True) or {}
    user_text  = (data.get('message') or "").strip()
    session_id = (data.get('session_id') or "").strip()  # nhận từ frontend
    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    add_message("user", user_text, session_id=session_id)
    full_start = time.time()

    # 1) EMBED TIME
    try:
        t0 = time.time()
        _ = embeddings.embed_query("query: " + user_text)
        embed_time = time.time() - t0
    except Exception:
        embed_time = 0.0

    # 2) HYBRID RETRIEVE + RERANK
    docs_text, search_time = "", 0.0
    try:
        t0 = time.time()
        candidates = retriever.get_relevant_documents("query: " + user_text)
        ranked = rerank(user_text, candidates, top_k=TOP_K)

        parts, total = [], 0
        for d, _score in ranked:
            txt = d.page_content
            if txt.lower().startswith("passage: "):
                txt = txt[len("passage: "):]
            parts.append(txt)
            total += len(txt)
            if total > 4000:
                break
        docs_text = "\n\n---\n\n".join(parts) if parts else ""
        search_time = time.time() - t0
    except Exception:
        pass

    # 3) Prompt
    context_hint = f"Context (trích từ tài liệu):\n{docs_text}" if docs_text else "(Không tìm thấy dữ liệu context phù hợp.)"
    system_prompt = f"""{SYSTEM_PRIMER}

- Bạn là trợ lý trả lời dựa trên ngữ cảnh được cung cấp.
- Nếu thông tin không có trong context, hãy nói 'không có trong dữ liệu'.
- Trích dẫn ngắn nguồn (source, chunk) khi có thể.
{context_hint}
"""

    hist_msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in get_history() if m["role"] in ("user", "assistant")
    ]
    contents = _to_gemini_history_no_system(hist_msgs)

    first_user_text = f"""[SYSTEM]
{system_prompt}

[USER]
{user_text}"""
    contents.append({"role": "user", "parts": [{"text": first_user_text}]})

    # 4) Gọi Gemini
    try:
        t0 = time.time()
        resp = gclient.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=GEN_CFG
        )
        result = getattr(resp, "text", "") or ""
        llm_time = time.time() - t0
    except Exception as e:
        result = f"Lỗi khi gọi Gemini API: {e}"
        llm_time = 0.0

    add_message("assistant", result, session_id=session_id)
    elapsed = time.time() - full_start

    return jsonify({
        "ok": True,
        "answer": result,
        "timing": {
            "total": round(elapsed, 2),
            "embedding": round(embed_time, 2),
            "search": round(search_time, 2),
            "llm": round(llm_time, 2)
        }
    })

@app.route('/chat', methods=['POST'])
@login_required(api=True)
def chat_api_alias():
    return chat_api()

# =====================================
# Marketing views
# =====================================
@app.route("/marketing/rephrase")
@login_required(roles=['marketing'])
def page_rephrase():
    return render_template("marketing/rephrase.html")

@app.route("/marketing/tiktok")
@login_required(roles=['marketing'])
def page_tiktok():
    return render_template("marketing/tiktok.html")

@app.route("/marketing/fab")
@login_required(roles=['marketing'])
def page_fab():
    return render_template("marketing/fab.html")

# =====================================
# Saves APIs
# =====================================
@app.route("/api/saves", methods=["GET"])
@login_required(api=True)
def api_saves():
    item_type = request.args.get("type", "fbads")
    return jsonify({"items": get_items(item_type)})

@app.route("/api/save", methods=["POST"])
@login_required(api=True)
def api_save():
    payload = request.get_json() or {}
    item_type = payload.get("type", "fbads")
    text = payload.get("text", "")
    input_data = payload.get("input", {})
    meta = payload.get("meta", {})
    if not text:
        return jsonify({"error": "Thiếu nội dung để lưu."}), 400
    saved_item = save_item(item_type, text, input_data, meta)
    return jsonify({"ok": True, "saved": saved_item})

@app.route("/api/saves/delete", methods=["POST"])
@login_required(api=True)
def api_delete():
    payload = request.get_json() or {}
    item_type = payload.get("type", "fbads")
    timestamp = payload.get("ts")
    if timestamp is None:
        return jsonify({"error": "Thiếu ts"}), 400
    success = delete_item(item_type, timestamp)
    return jsonify({"ok": success})

# =====================================
# Generation APIs (giữ nguyên như bản trước)
# =====================================
@app.route("/api/fbads/generate_text", methods=["POST"])
@login_required(api=True, roles=['marketing'])
def api_fb_text():
    data = request.get_json() or {}
    product  = data.get("product_desc", "")
    customer = data.get("customer", "")
    lang     = data.get("lang", "Tiếng Việt")
    brand    = (data.get("brand") or "").strip() or "Tiximax Logistics"
    tone     = (data.get("tone") or "Chuyên nghiệp").strip()

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
        text = call_gemini_flash(u_prompt, sys_inst, [SystemMessage(persona_vi)])
        latency = time.time() - t0
        return jsonify({"text": text, "meta": {"latency_sec": round(latency, 2)}})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo nội dung: {str(e)}"}), 500

@app.route("/api/fbads/generate_images", methods=["POST"])
@login_required(api=True, roles=['marketing'])
def api_fb_imgs():
    form_data = request.form

    result_text  = form_data.get("result_text", "")
    product      = form_data.get("product_desc", "")
    customer     = form_data.get("customer", "")
    brand        = (form_data.get("brand", "") or "").strip() or "Tiximax Logistics"
    engine_label = form_data.get("engine_label", "Gemini 2.0 Flash")
    aspect       = (form_data.get("aspect", "1:1") or "1:1").strip()
    if aspect not in ALLOWED_ASPECTS:
        aspect = "1:1"
    style        = form_data.get("style_preset", "Semi-realistic")
    composition  = form_data.get("composition", "Lifestyle scene")

    add_logo    = form_data.get("add_logo", "false").lower() == "true"
    keep_logo   = form_data.get("keep_logo_original", "true").lower() == "true"
    logo_scale  = float(form_data.get("logo_scale", 0.15))
    logo_margin = int(form_data.get("logo_margin", 20))

    logo_img = None
    if request.files.get("logo_file"):
        try:
            logo_img = Image.open(request.files["logo_file"].stream).convert("RGBA")
        except Exception:
            logo_img = None
    elif add_logo:
        try:
            logo_img = load_default_logo(app.root_path)
        except Exception:
            default_path = os.path.join(app.root_path, "static", "images", "logo.png")
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
            include_logo=(not add_logo)
        )

    try:
        prompt_en = ensure_english_prompt(prompt_raw)
        engine = "gemini2" if engine_label == "Gemini 2.0 Flash" else "imagen4"
        images = generate_image_via_gemini_api(
            prompt_en, engine=engine, aspect_ratio=aspect, n_images=2
        )

        images = [conform_aspect(im, aspect, mode="crop", bg="#FFFFFF") for im in (images or [])]

        if add_logo and images:
            if logo_img is None:
                return jsonify({"error": "Không tìm thấy logo (static/images/logo.png) hoặc file upload."}), 400
            images = add_logo_to_images(
                images, logo_img, margin=logo_margin, keep_original=keep_logo, scale=logo_scale
            )

        return jsonify({"images": [pil_to_base64(img) for img in images], "used_prompt": prompt_en})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo ảnh: {str(e)}"}), 500

@app.route("/api/rephrase", methods=["POST"])
@login_required(api=True, roles=['marketing'])
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

@app.route("/api/tiktok", methods=["POST"])
@login_required(api=True, roles=['marketing'])
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

@app.route("/api/fab", methods=["POST"])
@login_required(api=True, roles=['marketing'])
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

# =====================================
# Planner APIs (giữ nguyên logic cũ)
# =====================================
@app.route("/marketing/planner")
@login_required(roles=['marketing'])
def marketing_planner():
    return render_template("marketing/planner.html", active="marketing")

@app.route("/api/planner/generate", methods=["POST"])
@login_required(roles=['marketing'])
def api_planner_generate():
    d = request.get_json(silent=True) or {}
    goal       = d.get("goal") or (d.get("objectives") or [None])[0]
    channel_in = d.get("channel", "")
    channel    = _normalize_channel(channel_in)
    tones      = d.get("tones", [])
    lang       = d.get("lang", "Tiếng Việt")

    system_prompt = _build_system_prompt_ifelse(channel, goal, tones, lang)
    up_body = build_user_prompt_body({**d, "channel": channel})
    up, sp = apply_occasion_lock(up_body, system_prompt)

    t0 = time.time()
    try:
        text = call_gemini_flash(up, sp, [SystemMessage(persona_vi)])
    except Exception as e:
        return jsonify({"error": f"Lỗi LLM: {e}"}), 500
    dt = time.time() - t0

    return jsonify({
        "text": text,
        "meta": {"latency_sec": round(dt, 2), "channel": channel or "N/A", "goal": goal or "N/A"}
    })

# =====================================
# History APIs (NEW for sessions)
# =====================================
def _read_sessions_and_messages(username: str):
    """
    Trả về dict: session_id -> list[{role, content, ts}]
    Tin cũ (không có cột session_id) sẽ gom vào 'default'.
    """
    p = Path(CHAT_LOGS_DIR) / f"{username}.csv"
    sessions = {}
    if not p.exists():
        return sessions

    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        has_sid = 'session_id' in (reader.fieldnames or [])
        for r in reader:
            sid = (r.get('session_id') or "").strip() if has_sid else "default"
            role = (r.get('role') or "").strip()
            content = r.get('content') or ""
            ts = (r.get('ts_utc') or r.get('ts_local') or "").strip()
            if not content:
                continue
            sessions.setdefault(sid, []).append({"role": role, "content": content, "ts": ts})

    for sid in sessions:
        sessions[sid].sort(key=lambda x: x.get("ts") or "")
    return sessions

@app.route("/api/history", methods=["GET"])
@login_required(api=True)
def api_history():
    """Giữ API cũ: trả N tin gần nhất (không phân session)"""
    user = session.get("user")
    if not user:
        return jsonify({"items": []})
    limit = int(request.args.get("limit", 50))
    sessions = _read_sessions_and_messages(user)
    flat = []
    for sid, msgs in sessions.items():
        for m in msgs:
            flat.append({**m, "session_id": sid})
    flat.sort(key=lambda x: x.get("ts") or "")
    return jsonify({"items": flat[-min(limit, MAX_HISTORY):]})

@app.route("/api/history/sessions", methods=["GET"])
@login_required(api=True)
def api_history_sessions():
    """Liệt kê các đoạn chat theo CSV"""
    user = session.get("user")
    if not user:
        return jsonify({"sessions": []})
    sessions = _read_sessions_and_messages(user)
    out = []
    for sid, msgs in sessions.items():
        if not msgs:
            continue
        first_user = next((m for m in msgs if m["role"] == "user"), None)
        title = (first_user["content"][:30] if first_user else "Cuộc trò chuyện") if sid != "default" else "Mặc định"
        out.append({
            "id": sid,
            "title": title,
            "count": len(msgs),
            "first_ts": msgs[0]["ts"],
            "last_ts": msgs[-1]["ts"],
        })
    out.sort(key=lambda x: x["last_ts"], reverse=True)
    return jsonify({"sessions": out})

@app.route("/api/history/by_session", methods=["GET"])
@login_required(api=True)
def api_history_by_session():
    """Lấy tin nhắn theo session_id"""
    user = session.get("user")
    if not user:
        return jsonify({"items": []})
    sid = (request.args.get("session_id") or "").strip() or "default"
    sessions = _read_sessions_and_messages(user)
    items = sessions.get(sid, [])
    return jsonify({"items": items})

# =====================================
# Main
# =====================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
