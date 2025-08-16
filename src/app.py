import os, json, time
import time
import csv
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo
from PIL import Image

from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from werkzeug.security import check_password_hash, generate_password_hash
import requests
from langchain_core.messages import SystemMessage
# Import helper modules
from Helpers.Data_storage import save_item, delete_item, get_items
from Helpers.LLM_client import apply_occasion_lock, call_gemini_flash, extract_image_prompt, ensure_english_prompt 
from Helpers.prompt_KT import persona_vi
from Helpers.Image_generation_and_processing import (
    build_image_prompt, generate_image_via_gemini_api,
    add_logo_to_images, pil_to_base64, load_default_logo
)
from Helpers.Content_generation import (
    generate_facebook_ads_content, generate_rephrase_content,
    generate_tiktok_content, generate_fab_content
)
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
USERS_CSV = os.environ.get("USERS_CSV", "./src/users.csv")
SAVES_DIR = os.path.join(os.path.dirname(__file__), "Data", "saves")
os.makedirs(SAVES_DIR, exist_ok=True)

def load_users():
    users = {}
    if not os.path.exists(USERS_CSV):
        return users
    with open(USERS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            u = (row.get('username') or '').strip()
            ph = (row.get('password_hash') or '').strip()
            pw = (row.get('password') or '').strip()
            if not u:
                continue
            if ph:
                users[u] = {'password_hash': ph}
            elif pw:
                users[u] = {'password_hash': generate_password_hash(pw)}
    return users

USERS = load_users()

def login_required(view=None, *, api=False):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user'):
                if api:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for('login', next=request.path))
            return fn(*args, **kwargs)
        return wrapped
    return deco(view) if view else deco

# =====================================
# Model & VectorStore init (one-time)
# =====================================
EMBED_MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "./src/models/local_e5_large_v2")
FAISS_DIR = os.environ.get("FAISS_DIR", "./src/FAISS_Vector")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://192.168.2.8:1234/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-3n-e4b-it-text")

try:
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL_DIR,
        encode_kwargs={"normalize_embeddings": True}
    )
    vector_store = FAISS.load_local(
        FAISS_DIR, embeddings, allow_dangerous_deserialization=True
    )
except Exception as e:
    raise RuntimeError(f"Failed to init FAISS/embeddings: {e}")

# =====================================
# Logging config (CSV)
# =====================================
CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _log_message_to_csv(username: str, role: str, content: str, ts_utc_iso: str):
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
            writer.writerow(['ts_utc', 'ts_local', 'username', 'role', 'content'])
        writer.writerow([ts_utc_iso, ts_local_iso, username, role, content])

# =====================================
# Helpers
# =====================================
SYSTEM_PRIMER = (
    "Bạn là trợ lý AI thông minh của Công ty Tiximax Logistic. "
    "Bạn chuyên hỗ trợ cung cấp các thông tin của công ty dựa theo các tài liệu đã đưa vào. "
    "Bạn sẽ hỗ trợ cho các phòng ban như quản lý, sale, tiếp thị và nhân sự. "
    "Trả lời bằng các từ ngữ dễ nghe, phù hợp với chuyên ngành. Nếu bạn không có thông tin trả lời, cứ nói tôi không biết."
)

MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "50"))

def get_history():
    msgs = session.get("messages") or []
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
        session["messages"] = msgs
    return msgs

def add_message(role, content):
    msgs = get_history()
    ts_utc_iso = datetime.now(timezone.utc).isoformat()
    msgs.append({"role": role, "content": content, "ts": ts_utc_iso})
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
    session["messages"] = msgs

    try:
        _log_message_to_csv(session.get('user'), role, content, ts_utc_iso)
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
@login_required
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

# =====================================
# Chat APIs (protected)
# =====================================
@app.get('/api/chat/history')
@login_required(api=True)
def chat_history():
    limit = min(int(request.args.get('limit', 30)), 100)
    return jsonify({"ok": True, "messages": get_history()[-limit:]})

@app.route('/api/chat', methods=['POST'])
@login_required(api=True)
def chat_api():
    data = request.get_json(force=True)
    user_text = (data or {}).get('message', '').strip()
    if not user_text:
        return jsonify({"error": "Missing message"}), 400

    add_message("user", user_text)
    full_start = time.time()

    try:
        t0 = time.time()
        q_vec = embeddings.embed_query(user_text)
        embed_time = time.time() - t0
    except Exception:
        embed_time = 0.0
        q_vec = None

    docs_text = ""
    try:
        t0 = time.time()
        if q_vec is not None:
            docs = vector_store.similarity_search_by_vector(q_vec, k=3)
            search_time = time.time() - t0
            docs_text = "\n".join(d.page_content for d in docs)
        else:
            search_time = 0.0
    except Exception:
        search_time = 0.0

    context_hint = f"Context: {docs_text}" if docs_text else "(Không tìm thấy dữ liệu context phù hợp.)"
    system_prompt = f"{SYSTEM_PRIMER}\n{context_hint}"

    history_msgs = [{"role": "system", "content": system_prompt}]
    history_msgs += [
        {"role": m["role"], "content": m["content"]}
        for m in get_history() if m["role"] in ("user", "assistant")
    ]

    try:
        t0 = time.time()
        resp = requests.post(
            LLM_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json={
                "model": LLM_MODEL,
                "messages": history_msgs,
                "temperature": 0.5,
                "max_tokens": 512
            },
            timeout=(5, 120)
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"]
        llm_time = time.time() - t0
    except Exception as e:
        result = f"Lỗi khi gọi LLM local API: {e}"
        llm_time = 0.0

    add_message("assistant", result)
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
# Marketing pages (views)
# =====================================
@app.route("/marketing/rephrase")
def page_rephrase():
    return render_template("marketing/rephrase.html")

@app.route("/marketing/tiktok")
def page_tiktok():
    return render_template("marketing/tiktok.html")

@app.route("/marketing/fab")
def page_fab():
    return render_template("marketing/fab.html")

# =====================================
# Saves APIs (NO rename)
# =====================================
@app.route("/api/saves", methods=["GET"])
def api_saves():
    item_type = request.args.get("type", "fbads")
    return jsonify({"items": get_items(item_type)})

@app.route("/api/save", methods=["POST"])
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
def api_delete():
    payload = request.get_json() or {}
    item_type = payload.get("type", "fbads")
    timestamp = payload.get("ts")
    if timestamp is None:
        return jsonify({"error": "Thiếu ts"}), 400
    success = delete_item(item_type, timestamp)
    return jsonify({"ok": success})

# =====================================
# Generation APIs
# =====================================
@app.route("/api/fbads/generate_text", methods=["POST"])
def api_fb_text():
    """Generate Facebook Ads text content"""
    data = request.get_json() or {}
    product  = data.get("product_desc", "")
    customer = data.get("customer", "")
    lang     = data.get("lang", "Tiếng Việt")
    brand    = (data.get("brand") or "").strip() or "Tiximax Logistics"
    tone     = (data.get("tone") or "Chuyên nghiệp").strip()

    if not product or not customer:
        return jsonify({"error": "Thiếu dữ liệu bắt buộc."}), 400

    # Dựng user_prompt: nhét đầy đủ brand/tone/lang + yêu cầu format
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
    
    # Áp khóa theo dịp (chỉ thêm constraint, không phá cấu trúc)
    u_prompt, sys_inst = apply_occasion_lock(user_prompt, persona_vi)

    # Gọi model theo flow cũ (không dùng generate_facebook_ads_content vì chưa thấy định nghĩa)
    try:
        t0 = time.time()
        text = call_gemini_flash(u_prompt, sys_inst, [SystemMessage(persona_vi)])
        latency = time.time() - t0
        return jsonify({"text": text, "meta": {"latency_sec": round(latency, 2)}})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo nội dung: {str(e)}"}), 500
    

@app.route("/api/fbads/generate_images", methods=["POST"])
def api_fb_imgs():
    """Generate Facebook Ads images"""
    form_data = request.form

    # Extract form parameters
    result_text = form_data.get("result_text", "")
    product     = form_data.get("product_desc", "")
    customer    = form_data.get("customer", "")
    brand       = (form_data.get("brand", "") or "").strip() or "Tiximax Logistics"
    engine_label = form_data.get("engine_label", "Gemini 2.0 Flash")
    aspect      = form_data.get("aspect", "1:1")
    style       = form_data.get("style_preset", "Semi-realistic")
    composition = form_data.get("composition", "Lifestyle scene")

    # Logo settings
    add_logo    = form_data.get("add_logo", "false").lower() == "true"
    keep_logo   = form_data.get("keep_logo_original", "true").lower() == "true"
    logo_scale  = float(form_data.get("logo_scale", 0.15))
    logo_margin = int(form_data.get("logo_margin", 20))

    # Handle logo image
    logo_img = None
    if request.files.get("logo_file"):
        try:
            logo_img = Image.open(request.files["logo_file"].stream).convert("RGBA")
        except Exception:
            logo_img = None
    elif add_logo:
        # dùng helper mặc định nếu bạn có; nếu không, fallback thủ công
        try:
            logo_img = load_default_logo(app.root_path)  # Helper của bạn
        except Exception:
            default_path = os.path.join(app.root_path, "static", "images", "logo.png")
            if os.path.exists(default_path):
                try:
                    logo_img = Image.open(default_path).convert("RGBA")
                except Exception:
                    logo_img = None

    # Generate or extract image prompt
    prompt_raw = extract_image_prompt(result_text) if result_text else None
    if not prompt_raw:
        # subject có brand để gợi đúng tinh thần thương hiệu (không in text trong ảnh)
        subject = f"{brand} – {product} (audience: {customer})"
        prompt_raw = build_image_prompt(
            subject=subject,
            aspect_ratio=aspect,
            style=style,
            composition=composition,
            include_logo=(not add_logo)  # nếu đã add_logo bằng overlay thì tránh ép generator gắn thêm
        )

    # Ensure English prompt and generate images
    try:
        prompt_en = ensure_english_prompt(prompt_raw)
        engine = "gemini2" if engine_label == "Gemini 2.0 Flash" else "imagen4"
        images = generate_image_via_gemini_api(prompt_en, engine=engine, aspect_ratio=aspect, n_images=2)

        # Add logo if requested
        if add_logo and images:
            if logo_img is None:
                return jsonify({"error": "Không tìm thấy logo (static/images/logo.png) hoặc file upload."}), 400
            images = add_logo_to_images(images, logo_img, margin=logo_margin, keep_original=keep_logo, scale=logo_scale)

        return jsonify({"images": [pil_to_base64(img) for img in images], "used_prompt": prompt_en})
    except Exception as e:
        return jsonify({"error": f"Lỗi khi tạo ảnh: {str(e)}"}), 500

@app.route("/api/rephrase", methods=["POST"])
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
# Main
# =====================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
