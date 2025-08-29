# src/routes/transcribe.py
import os
import time
from flask import Blueprint, jsonify, request, render_template, session, current_app
from werkzeug.utils import secure_filename

from app.Login.login_required import login_required
from app.Helpers.media_convert import convert_to_wav16k_mono
from app.Helpers.vinai_stt import transcribe_file

bp = Blueprint("stt", __name__)

# -----------------------------------------------------------------------------
# Alias cũ cho compat: một số JS có thể POST lên /tools/stt
# -----------------------------------------------------------------------------
@bp.route("/tools/stt", methods=["POST"])
@login_required(api=True)
def api_transcribe_alias():
    return api_transcribe()

# -----------------------------------------------------------------------------
# API: POST /transcribe  (multipart/form-data: audio=<file>, lang=vi|en|auto)
# Trả JSON: { ok, text, segments, filename } hoặc { error }
# -----------------------------------------------------------------------------
@bp.route("/transcribe", methods=["POST"])
@login_required(api=True)
def api_transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Thiếu file 'audio' (multipart/form-data)."}), 400

    audio = request.files["audio"]
    if not audio or not audio.filename:
        return jsonify({"error": "Tên file trống."}), 400

    lang = (request.form.get("lang") or "vi").strip().lower()

    # Lưu tạm file upload
    upload_dir = os.path.join(current_app.root_path, "app", "Data_app", "uploads", "stt")
    os.makedirs(upload_dir, exist_ok=True)
    fname = f"{int(time.time()*1000)}_{secure_filename(audio.filename)}"
    src_path = os.path.join(upload_dir, fname)
    audio.save(src_path)

    # Chuẩn hoá sang WAV 16k mono (ổn định cho mọi nguồn: mp4/webm/m4a/…)
    try:
        base, ext = os.path.splitext(src_path)
        wav_path = base + "_16k.wav" if ext.lower() == ".wav" else base + ".wav"
        path_for_asr = convert_to_wav16k_mono(src_path, wav_path)
    except Exception as conv_e:
        return jsonify({"error": f"Không chuyển được sang WAV: {conv_e}"}), 400

    # Nhận dạng
    try:
        text, segments = transcribe_file(path_for_asr, lang=lang)
        if not (text or "").strip():
            return jsonify({
                "error": (
                    "Không nhận được tiếng nói (kết quả rỗng). "
                    "Hãy chọn đúng ngôn ngữ, kiểm tra âm lượng/ồn nền, hoặc thử file khác."
                )
            }), 200
        return jsonify({
            "ok": True,
            "text": text,
            "segments": segments,
            "filename": os.path.basename(path_for_asr),
        })
    except Exception as e:
        return jsonify({"error": f"ASR failed: {e}"}), 500

# -----------------------------------------------------------------------------
# PAGE: GET /transcribe → trả về trang HTML
# Endpoint name: stt.transcribe  (để khớp với template: url_for('stt.transcribe'))
# -----------------------------------------------------------------------------
@bp.route("/transcribe", methods=["GET"])
@login_required
def transcribe():
    return render_template(
        "home/transcribe.html",
        current_user=session.get("user"),
        active="transcribe",
    )
