import tempfile
import os, json, time, csv, uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from PIL import Image

import fitz
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, stream_with_context, Response, send_file
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
import requests
import threading, json
# LangChain / LLM helpers
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.messages import SystemMessage

# Import helper modules
from src.Helpers.Data_storage import save_item, delete_item, get_items
from src.Helpers.LLM_client import apply_occasion_lock, call_gemini_flash, extract_image_prompt, ensure_english_prompt
from src.Helpers.media_convert import convert_to_wav16k_mono
from src.Helpers.prompt_KT import persona_vi
from src.Helpers.Image_generation_and_processing import (
    build_image_prompt, generate_image_via_gemini_api,
    add_logo_to_images, pil_to_base64, load_default_logo,
    conform_aspect, ALLOWED_ASPECTS
)
from src.Helpers.Content_generation import (
    generate_facebook_ads_content, generate_rephrase_content,
    generate_tiktok_content, generate_fab_content
)
from src.Helpers.prompt_internal import SYSTEM_PRIMER
from src.Helpers.vinai_stt import transcribe_file
from src.Login.login_required import load_users, login_required
# from Login.Logging_config import _log_message_to_csv 
from src.Helpers.Marketing_Planner.Content_Planner import (
    _describe_builtin_channel, _describe_custom_channel, _normalize_channel, _build_system_prompt_ifelse, build_user_prompt_body
)
try:
    from src.Model_LLM.hybrid_retriever import rerank, TOP_K  # khi chạy -m src.app
    from src.Helpers.Marketing_Planner.channels_store import (
    list_all_for_planner, load_channels, create_channel, update_channel,
    delete_channel, get_by_name )
    from src.Processing_Data.Pdf_Images_to_Text import pdf_to_txt_vi
except ImportError:
    from src.Model_LLM.hybrid_retriever import rerank, TOP_K
    from src.Helpers.Marketing_Planner.channels_store import (
    list_all_for_planner, load_channels, create_channel, update_channel,
    delete_channel, get_by_name
    )
    from src.Processing_Data.Pdf_Images_to_Text import pdf_to_txt_vi

from src.Helpers.rate_limit import get_text_limiter
from zoneinfo import ZoneInfo
from src.Model_LLM.model_llm import LLM_model
from google.genai import types as genai_types
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
load_dotenv()
# =====================================
# Flask setup
# =====================================
app = Flask(__name__,
    template_folder="src/templates",
    static_folder="src/static",)

app.config.from_object('src.config.Config')  # SECRET_KEY etc.
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
# --- semaphore cho tuyến gọi thẳng bằng gclient (không qua Helpers/LLM_client) ---
LLM_SEM = threading.Semaphore(int(os.environ.get("SEM_LLM", "24")))

def _estimate_from_contents(contents, max_out_tokens=1024):
    words = 0
    for m in contents or []:
        for p in (m.get("parts") or []):
            if isinstance(p, dict) and p.get("text"):
                words += len(p["text"].split())
    return int(1.3 * words) + int(max_out_tokens or 512)

def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
    limiter = get_text_limiter()
    max_out = config.get("max_output_tokens") if isinstance(config, dict) else getattr(config, "max_output_tokens", 1024)
    tokens_est = _estimate_from_contents(contents, max_out)
    last_err = None
    for i in range(retries + 1):
        try:
            limiter.acquire(tokens_est)
            t0 = time.time()
            with LLM_SEM:
                resp = gclient.models.generate_content(model=model, contents=contents, config=config)
            limiter.on_success()
            return (getattr(resp, "text", "") or ""), time.time() - t0
        except Exception as e:
            last_err = e
            s = str(e).lower()
            if ("429" in s or "quota" in s or "rate" in s) and i < retries:
                limiter.on_429()
                time.sleep(backoff * (2 ** i))
                continue
            limiter.on_429()
            raise last_err

# =====================================
# Constants & Settings
# =====================================
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "50"))
CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

# =====================================
# CSV logging (WITH session_id)
# =====================================


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

    def _is_hashed(s: str) -> bool:
        s = s or ""
        return s.startswith(("pbkdf2:", "scrypt:", "argon2:", "bcrypt:"))

    if (not user) or (not password):
        return render_template("home/login.html",
                            error="Tên đăng nhập hoặc mật khẩu không đúng.",
                            next_url=request.form.get("next",""))

    stored_hash  = user.get("password_hash") or ""
    stored_plain = user.get("password_plain") or ""

    ok = False
    try:
        if _is_hashed(stored_hash):
            ok = check_password_hash(stored_hash, password)
        else:
            # CSV đang lưu plain ở cột password hoặc password_hash (trường hợp hiếm)
            ok = (password == stored_plain) or (password == stored_hash)
    except Exception:
        # fallback cuối cùng
        ok = (password == stored_plain)

    if not ok:
        return render_template("home/login.html",
                            error="Tên đăng nhập hoặc mật khẩu không đúng.",
                            next_url=request.form.get("next",""))

    # --- Đăng nhập thành công ---
    session.clear()
    session.permanent = remember
    session['user'] = username
    session['role'] = (user.get('role') or '').strip()
    session['roles'] = user.get('roles', [])      # QUAN TRỌNG
    session['messages'] = []
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
@login_required(roles=['marketing', 'manager_marketing'])
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
# LỌC 
import re

_SOURCE_TAG_PAT = re.compile(
    r"""\s*[\(\[](?=[^)\]]{0,240}?\b(?:source|nguồn|chunk)\b)[^)\]]+[\)\]]""",
    re.IGNORECASE,
)

def strip_source_citations(text: str) -> str:
    if not text:
        return text
    text = _SOURCE_TAG_PAT.sub("", text)
    # dọn khoảng trắng/thừa dấu cách trước dấu câu
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()

# =====================================

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
        result, llm_time = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    except Exception as e:
        result = f"Lỗi khi gọi Gemini API: {e}"
        llm_time = 0.0
    result = strip_source_citations(result)
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
@login_required(roles=['marketing', 'manager_marketing'])
def page_rephrase():
    return render_template("marketing/rephrase.html")

@app.route("/marketing/tiktok")
@login_required(roles=['marketing', 'manager_marketing'])
def page_tiktok():
    return render_template("marketing/tiktok.html")

@app.route("/marketing/fab")
@login_required(roles=['marketing', 'manager_marketing'])
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
@login_required(api=True, roles=['marketing','manager_marketing'])
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
@login_required(api=True, roles=['marketing','manager_marketing'])
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

@app.route("/api/tiktok", methods=["POST"])
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

@app.route("/api/fab", methods=["POST"])
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

# =====================================
# Planner APIs (giữ nguyên logic cũ)
# =====================================
@app.route("/marketing/planner")
@login_required(roles=['marketing', 'manager_marketing'])
def marketing_planner():
    return render_template("marketing/planner.html", active="marketing")

@app.route("/api/planner/generate", methods=["POST"])
@login_required(roles=['marketing', 'manager_marketing'])
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



# ==================================== lannner new ==========================

# ========= Channels: UI =========
@app.route("/marketing/channels")
@login_required(roles=['admin', 'manager_marketing'])
def marketing_channels():
    return render_template("marketing/channels.html", active="marketing")

# ========= Channels: APIs =========
def _merge_channels_for_planner():
    # Lấy kênh builtin (mặc định)
    try:
        builtin = list_all_for_planner() or []
    except Exception:
        builtin = []

    # Lấy kênh custom (admin/manager tạo)
    try:
        custom = load_channels() or []
    except Exception:
        custom = []

    # Hợp nhất + bỏ trùng theo id/name, bỏ kênh archived
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

@app.route("/api/channels", methods=["GET"])
@login_required(roles=['marketing', 'manager_marketing'])
def api_channels_list():
    return jsonify({"items": _merge_channels_for_planner()})



@app.route("/api/channels/custom", methods=["GET"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_list_custom():
    return jsonify({"items": load_channels()})

@app.route("/api/channels", methods=["POST"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_create():
    d = request.get_json(silent=True) or {}
    try:
        item = create_channel(d)
        return jsonify(item), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/channels/<cid>", methods=["PUT","PATCH"])
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

@app.route("/api/channels/<cid>", methods=["DELETE"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_delete(cid):
    try:
        delete_channel(cid)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/channels/prompt", methods=["POST"])
@login_required(roles=['admin', 'manager_marketing'])
def api_channels_prompt():
    d = request.get_json(silent=True) or {}
    channel_in = d.get("channel", "")
    lang       = d.get("lang", "Tiếng Việt")
    tones      = d.get("tones", [])

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
        result = call_gemini_flash(sys_ask, "", [SystemMessage(persona_vi)])
    except Exception as e:
        return jsonify({"error": f"Lỗi gọi Gemini: {e}"}), 500

    return jsonify({"channel": channel, "generated": result})

@app.route('/api/chat/stream', methods=['POST'])
@login_required(api=True)
def chat_stream():
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model()

    data = request.get_json(force=True) or {}
    user_text  = (data.get('message') or "").strip()
    session_id = (data.get('session_id') or "").strip()
    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    add_message("user", user_text, session_id=session_id)

    # (tùy bạn) rút gọn phần embed/retrieve cho stream hoặc giữ nguyên như chat_api()
    hist_msgs = [{"role": m["role"], "content": m["content"]}
                 for m in get_history() if m["role"] in ("user", "assistant")]
    contents = _to_gemini_history_no_system(hist_msgs)

    context_hint = "(Stream mode - context omitted)"  # hoặc ghép docs_text nếu muốn
    system_prompt = f"""{SYSTEM_PRIMER}
    - Bạn là trợ lý trả lời dựa trên ngữ cảnh được cung cấp (nếu có).
    {context_hint}
    """
    first_user_text = f"""[SYSTEM]
    {system_prompt}

    [USER]
    {user_text}"""
    contents.append({"role": "user", "parts": [{"text": first_user_text}]})
    limiter = get_text_limiter()
    tokens_est = _estimate_from_contents(contents, GEN_CFG.get("max_output_tokens", 1024))

    def gen():
        yield "event: ready\ndata: {}\n\n"
        try:
            limiter.acquire(tokens_est)
            with LLM_SEM:
                resp = gclient.models.generate_content(
                    model=GEMINI_MODEL, contents=contents, config=GEN_CFG, stream=True
                )
                acc = []
                for ev in resp:
                    chunk = getattr(ev, "text", "") or ""
                    if chunk:
                        acc.append(chunk)
                        yield f"data: {json.dumps({'delta': chunk})}\n\n"
                    else:
                        yield ": keep-alive\n\n"
            limiter.on_success()
            # Lưu full answer
            full_answer = "".join(acc).strip()
            add_message("assistant", full_answer, session_id=session_id)
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            limiter.on_429()
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# =========================== PDF to TXT ====================================



# --- DÁN THÊM/THAY THẾ HÀM LÀM SẠCH Ở BẤT KỲ ĐÂU TRƯỚC ROUTE:
def _clean_extracted_text(s: str) -> str:
    if not s:
        return ""
    # lọc ký tự form feed
    s = s.replace("\x0c", "\n")
    # bỏ dòng toàn số (thường số trang)
    lines = [ln.strip() for ln in s.splitlines()]
    out = []
    for ln in lines:
        if (ln.isdigit() and len(ln) <= 3) or (len(ln) == 1 and ln.isdigit()):
            continue
        out.append(ln)
    s2 = "\n".join(out)
    s2 = re.sub(r"\n{3,}", "\n\n", s2)      # gộp >2 dòng trống
    s2 = re.sub(r"[ \t]{2,}", " ", s2)      # gộp nhiều khoảng trắng
    return s2.strip()


@app.route("/api/pdf_to_txt", methods=["POST"])
@login_required(api=True)
def api_pdf_to_txt():
    """
    Nhận file PDF, ưu tiên gọi helper pdf_to_txt(...).
    - Nếu helper trả dict {text, txt_path}: dùng luôn
    - Nếu helper trả string path .txt: tự mở file đọc
    - Nếu helper trả text thô: dùng text
    - Nếu helper LỖI: Fallback tự trích PDF bằng PyMuPDF tại đây
    Trả về: {"text", "raw", "txt_path"}
    """
    if "file" not in request.files:
        return jsonify({"error": "Thiếu file PDF"}), 400

    pdf_in = request.files["file"]
    if not (pdf_in.filename or "").lower().endswith(".pdf"):
        return jsonify({"error": "File không phải PDF"}), 400

    # Lưu PDF tạm
    tmp_dir = tempfile.gettempdir()
    temp_pdf = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.pdf")
    pdf_in.save(temp_pdf)

    raw_text, txt_path = "", None

    def _fallback_extract(pdf_path: str):
        """Đọc PDF trực tiếp bằng PyMuPDF (không cần helper)."""
        text_chunks = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc, start=1):
                t = page.get_text("text") or ""
                if not t.strip():
                    # fallback blocks
                    try:
                        blocks = page.get_text("blocks") or []
                        t = "\n".join(
                            b[4] for b in blocks
                            if isinstance(b, (list, tuple)) and len(b) >= 5 and isinstance(b[4], str)
                        )
                    except Exception:
                        t = ""
                text_chunks.append(f"=== Page {i} ===\n{t.strip()}\n")
        text_all = "\n".join(text_chunks)

        # Lưu .txt tạm để UI có đường link download
        temp_txt = os.path.splitext(pdf_path)[0] + ".txt"
        try:
            with open(temp_txt, "w", encoding="utf-8") as f:
                f.write(text_all)
        except Exception:
            temp_txt = None
        return text_all, temp_txt

    try:
        # 1) Thử gọi helper của bạn (nếu có import đúng)
        try:
            result = pdf_to_txt_vi(temp_pdf)  # dùng import của bạn
        except Exception as helper_err:
            app.logger.warning("Helper pdf_to_txt() lỗi, dùng fallback: %s", helper_err)
            result = None

        if result is None:
            # 2) Fallback: tự trích bằng PyMuPDF
            raw_text, txt_path = _fallback_extract(temp_pdf)
        else:
            # 3) Chuẩn hóa mọi kiểu trả về của helper
            if isinstance(result, dict):
                raw_text = result.get("text") or ""
                txt_path = result.get("txt_path")
            elif isinstance(result, str):
                # Nếu là đường dẫn txt -> đọc file
                if os.path.exists(result) and result.lower().endswith(".txt"):
                    txt_path = result
                    try:
                        with open(result, "r", encoding="utf-8") as f:
                            raw_text = f.read()
                    except Exception:
                        raw_text = ""
                else:
                    # ít gặp: helper trả text luôn
                    raw_text = result or ""
            else:
                raw_text = getattr(result, "text", "") or ""
                txt_path = getattr(result, "txt_path", None)

            # Nếu helper không tạo file txt, tự tạo để có link download
            if not txt_path:
                tmp_txt = os.path.splitext(temp_pdf)[0] + ".txt"
                try:
                    with open(tmp_txt, "w", encoding="utf-8") as f:
                        f.write(raw_text or "")
                    txt_path = tmp_txt
                except Exception:
                    txt_path = None

        # Chuẩn hóa string
        if not isinstance(raw_text, str):
            try:
                if isinstance(raw_text, (list, tuple)):
                    raw_text = "\n".join(map(str, raw_text))
                else:
                    raw_text = str(raw_text)
            except Exception:
                raw_text = str(raw_text)

        cleaned = _clean_extracted_text(raw_text)
        username = session.get("user") or "anon"
        hist_txt_path = _save_history_txt(username, cleaned, pdf_in.filename)

        return jsonify({
            "ok": True,
            "text": cleaned,     # UI hiển thị
            "raw": raw_text,     # để debug nếu cần
            "txt_path": txt_path # cho nút Download
        })

    except Exception as e:
        app.logger.exception("PDF->TXT fatal: %s", e)
        return jsonify({"error": f"Lỗi xử lý PDF: {e}"}), 500

    finally:
        # Xoá PDF tạm
        try:
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)
        except Exception:
            pass


# ========= ZERO-CONFIG HELPERS (history lưu vào ./instance/pdf_txt/<user>/) =========
from werkzeug.utils import secure_filename

def _hist_user_dir(username: str) -> str:
    base = os.path.join(app.instance_path, "pdf_txt_111", secure_filename(username or "anon"))
    os.makedirs(base, exist_ok=True)
    return base

def _is_in_dir(path: str, base_dir: str) -> bool:
    try:
        return os.path.realpath(path).startswith(os.path.realpath(base_dir) + os.sep)
    except Exception:
        return False

def _save_history_txt(username: str, raw_text: str, orig_pdf_name: str) -> str:
    userdir = _hist_user_dir(username)
    ts = datetime.now(timezone.utc).astimezone(ZoneInfo(LOCAL_TZ_NAME)).strftime("%Y%m%d_%H%M%S")
    base_pdf = os.path.splitext(os.path.basename(orig_pdf_name or "document.pdf"))[0]
    fname = f"{ts}__{secure_filename(base_pdf)}.txt"
    out_path = os.path.join(userdir, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(raw_text or "")
    return out_path

def _list_history(username: str, limit: int = 50):
    userdir = _hist_user_dir(username)
    items = []
    for name in sorted(os.listdir(userdir), reverse=True):
        if not name.lower().endswith(".txt"):
            continue
        p = os.path.join(userdir, name)
        try:
            st = os.stat(p)
            items.append({
                "name": name,
                "path": p,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=ZoneInfo(LOCAL_TZ_NAME)).isoformat(),
            })
        except Exception:
            pass
    return items[:max(1, min(limit, 200))]

# =============================== ROUTES (API) ===============================

@app.route("/api/pdf_to_txt/history", methods=["GET"])
@login_required(api=True)
def api_pdf_to_txt_history():
    limit = int(request.args.get("limit", 50))
    user = session.get("user") or "anon"
    items = _list_history(user, limit=limit)
    # ẩn absolute path khỏi response, tạo URL download hợp lệ
    for it in items:
        it.pop("path", None)
        it["download_url"] = url_for(
            "api_pdf_to_txt_download",
            path=os.path.join(_hist_user_dir(user), it["name"])
        )
    return jsonify({"items": items})

@app.route("/api/pdf_to_txt/download", methods=["GET"])
@login_required(api=True)
def api_pdf_to_txt_download():
    p = request.args.get("path", "")
    userdir = _hist_user_dir(session.get("user") or "anon")
    if not p or not os.path.exists(p) or not _is_in_dir(p, userdir):
        return jsonify({"error": "Không tìm thấy file"}), 404
    return send_file(p, as_attachment=True, download_name=os.path.basename(p))

@app.route("/api/pdf_to_txt/delete", methods=["POST"])
@login_required(api=True)
def api_pdf_to_txt_delete():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name or not name.lower().endswith(".txt"):
        return jsonify({"error": "Thiếu hoặc sai tên file .txt"}), 400
    userdir = _hist_user_dir(session.get("user") or "anon")
    p = os.path.join(userdir, name)
    if not os.path.exists(p) or not _is_in_dir(p, userdir):
        return jsonify({"error": "Không tìm thấy file hợp lệ"}), 404
    try:
        os.remove(p)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": f"Xóa thất bại: {e}"}), 500

@app.route("/api/pdf_to_txt/save", methods=["POST"])
@login_required(api=True)
def api_pdf_to_txt_save():
    d = request.get_json(silent=True) or {}
    text = (d.get("text") or "").strip()
    base_name = (d.get("base_name") or "").strip()  # tên gợi ý (vd: abc.pdf)
    if not text:
        return jsonify({"error": "Không có nội dung để lưu."}), 400
    user = session.get("user") or "anon"
    try:
        orig = base_name or "manual_note"
        txt_path = _save_history_txt(user, text, orig)
        return jsonify({"ok": True, "txt_path": txt_path})
    except Exception as e:
        return jsonify({"error": f"Lưu thất bại: {e}"}), 500


@app.route("/pdf_to_txt", methods=["GET"])
@login_required
def page_pdf_to_txt():
    return render_template("home/pdf_to_txt.html", active="page_pdf_to_txt", current_user=session.get('user'))


# =====================================
# Pages (protected)
# =====================================
@app.route('/transcribe', methods=['POST'])
@login_required(api=True)
def api_transcribe():
    """
    Nhận form-data:
      - audio: <file audio/video>
      - lang:  vi | en | auto (mặc định vi)
    """
    if 'audio' not in request.files:
        return jsonify({"error": "Thiếu file 'audio' (multipart/form-data)."}), 400

    audio = request.files['audio']
    if not audio or not audio.filename:
        return jsonify({"error": "Tên file trống."}), 400

    lang = (request.form.get('lang') or 'vi').strip().lower()
    upload_dir = os.path.join(app.root_path, 'uploads', 'stt')
    os.makedirs(upload_dir, exist_ok=True)

    fname = f"{int(time.time()*1000)}_{secure_filename(audio.filename)}"
    src_path = os.path.join(upload_dir, fname)
    audio.save(src_path)

    # B1) Chuẩn hoá sang WAV 16k mono (ổn định cho mọi nguồn: mp4/webm/m4a/…)
    try:
        base, ext = os.path.splitext(src_path)
        # Nếu đã .wav thì tạo file _16k.wav; nếu không thì .wav luôn
        wav_path = base + "_16k.wav" if ext.lower() == ".wav" else base + ".wav"
        path_for_asr = convert_to_wav16k_mono(src_path, wav_path)
    except Exception as conv_e:
        app.logger.exception("Convert error: %s", conv_e)
        return jsonify({"error": f"Không chuyển được sang WAV: {conv_e}"}), 400

    # B2) Nhận dạng
    try:
        text, segments = transcribe_file(path_for_asr, lang=lang)
        if not (text or "").strip():
            return jsonify({
                "error": "Không nhận được tiếng nói (kết quả rỗng). "
                         "Hãy chọn đúng ngôn ngữ, kiểm tra âm lượng/ồn nền, hoặc thử file khác."
            }), 200
        return jsonify({
            "ok": True,
            "text": text,
            "segments": segments,
            "filename": os.path.basename(path_for_asr)
        })
    except Exception as e:
        app.logger.exception("ASR error: %s", e)
        return jsonify({"error": f"ASR failed: {e}"}), 500
    
# Alias để tương thích với JS cũ nếu nơi khác còn trỏ /tools/stt
@app.route('/tools/stt', methods=['POST'])
@login_required(api=True)
def api_transcribe_alias():
    return api_transcribe()

@app.route('/transcribe', methods=['GET'])
@login_required
def transcribe():
    return render_template(
        'home/transcribe.html',     
        current_user=session.get('user'),
        active='transcribe'         
    )

# =====================================
# Main
# =====================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
