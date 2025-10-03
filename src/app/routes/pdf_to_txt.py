import os, uuid, re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request, send_file, url_for, session, current_app, render_template
from app.Login.login_required import login_required
from werkzeug.utils import secure_filename
import fitz
# Helper from your Processing_Data
try:
    from app.Processing_Data.Pdf_Images_to_Text import pdf_to_txt_vi
except Exception:
    from app.Processing_Data.Pdf_Images_to_Text import pdf_to_txt_vi
bp = Blueprint('pdf', __name__)

def _clean_extracted_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\x0c", "\n") # form feed -> newline
    lines = [ln.strip() for ln in s.splitlines()]
    out = []
    for ln in lines:
        if (ln.isdigit() and len(ln) <= 3) or (len(ln) == 1 and ln.isdigit()):
            continue
        out.append(ln)
    s2 = "\n".join(out)
    s2 = re.sub(r"\n{3,}", "\n\n", s2)
    s2 = re.sub(r"[ \t]{2,}", " ", s2)
    return s2.strip()

def _hist_user_dir(username: str) -> str:
    base = os.path.join(current_app.instance_path, "pdf_txt_111", secure_filename(username or "anon"))
    os.makedirs(base, exist_ok=True)
    return base

def _tmp_user_dir(username: str) -> str:
    base = os.path.join(current_app.instance_path, "pdf_txt_tmp", secure_filename(username or "anon"))
    os.makedirs(base, exist_ok=True)
    return base

def _is_in_dir(path: str, base_dir: str) -> bool:
    try:
        return os.path.realpath(path).startswith(os.path.realpath(base_dir) + os.sep)
    except Exception:
        return False
    
def _save_history_txt(username: str, raw_text: str, orig_pdf_name: str) -> str:
    userdir = _hist_user_dir(username)
    ts = datetime.now(timezone.utc).astimezone(ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh"))).strftime("%Y%m%d_%H%M%S")
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
            from zoneinfo import ZoneInfo
            items.append({
                "name": name,
                "path": p,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh"))).isoformat(),
            })
        except Exception:
            pass
    return items[:max(1, min(limit, 200))]

# ---- routes ----
@bp.route("/api/pdf_to_txt", methods=["POST"])
@login_required(api=True)
def api_pdf_to_txt():
    if "file" not in request.files:
        return jsonify({"error": "Thiếu file PDF"}), 400
    pdf_in = request.files["file"]
    if not (pdf_in.filename or "").lower().endswith(".pdf"):
        return jsonify({"error": "File không phải PDF"}), 400

    user = session.get("user") or "anon"
    tmp_user = _tmp_user_dir(user)

    temp_pdf = os.path.join(tmp_user, f"{uuid.uuid4().hex}.pdf")
    pdf_in.save(temp_pdf)

    def _fallback_extract(pdf_path: str):
        text_chunks = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc, start=1):
                t = page.get_text("text") or ""
                if not t.strip():
                    try:
                        blocks = page.get_text("blocks") or []
                        t = "\n".join(b[4] for b in blocks if isinstance(b, (list, tuple)) and len(b) >= 5 and isinstance(b[4], str))
                    except Exception:
                        t = ""
                text_chunks.append(f"=== Page {i} ===\n{t.strip()}\n")
        return "\n".join(text_chunks)
    try:
        try:
            result = pdf_to_txt_vi(temp_pdf)
        except Exception:
            result = None

        if result is None:
            raw_text = _fallback_extract(temp_pdf)
        else:
            if isinstance(result, dict):
                raw_text = result.get("text") or ""
            elif isinstance(result, str):
                if os.path.exists(result) and result.lower().endswith(".txt"):
                    try:
                        with open(result, "r", encoding="utf-8") as f:
                            raw_text = f.read()
                    except Exception:
                        raw_text = ""
                else:
                    raw_text = result or ""
            else:
                raw_text = getattr(result, "text", "") or ""
        if not isinstance(raw_text, str):
            try:
                raw_text = "\n".join(map(str, raw_text)) if isinstance(raw_text, (list, tuple)) else str(raw_text)
            except Exception:
                raw_text = str(raw_text)
        cleaned = _clean_extracted_text(raw_text)
        ts = datetime.now(timezone.utc).astimezone(ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh"))).strftime("%Y%m%d_%H%M%S")
        base_pdf = os.path.splitext(os.path.basename(pdf_in.filename or "document.pdf"))[0]
        tmp_txt_name = f"{ts}__{secure_filename(base_pdf)}.txt"
        tmp_txt_path = os.path.join(tmp_user, tmp_txt_name)
        with open(tmp_txt_path, "w", encoding="utf-8") as f:
            f.write(cleaned or "")
        return jsonify({"ok": True, "text": cleaned, "raw": raw_text, "txt_path": tmp_txt_path})


    except Exception as e:
        return jsonify({"error": f"Lỗi xử lý PDF: {e}"}), 500
    finally:
        try:
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)
        except Exception:
            pass

@bp.route("/api/pdf_to_txt/history", methods=["GET"])
@login_required(api=True)
def api_pdf_to_txt_history():
    limit = int(request.args.get("limit", 50))
    user = session.get("user") or "anon"
    items = _list_history(user, limit=limit)
    for it in items:
        it.pop("path", None)
        it["download_url"] = url_for("pdf.api_pdf_to_txt_download", path=os.path.join(_hist_user_dir(user), it["name"]))
    return jsonify({"items": items})

@bp.route("/api/pdf_to_txt/download", methods=["GET"])
@login_required(api=True)
def api_pdf_to_txt_download():
    p = request.args.get("path", "")
    user = session.get("user") or "anon"
    user_hist = _hist_user_dir(user)
    user_tmp = _tmp_user_dir(user)
    p = os.path.normpath(p)
    if not p or not os.path.exists(p) or not (_is_in_dir(p, user_hist) or _is_in_dir(p, user_tmp)):
        return jsonify({"error": "Không tìm thấy file"}), 404
    return send_file(p, as_attachment=True, download_name=os.path.basename(p))

@bp.route("/api/pdf_to_txt/delete", methods=["POST"])
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
    
@bp.route("/api/pdf_to_txt/save", methods=["POST"])
@login_required(api=True)
def api_pdf_to_txt_save():
    d = request.get_json(silent=True) or {}
    text = (d.get("text") or "").strip()
    base_name = (d.get("base_name") or "").strip()
    if not text:
        return jsonify({"error": "Không có nội dung để lưu."}), 400
    user = session.get("user") or "anon"
    try:
        orig = base_name or "manual_note"
        txt_path = _save_history_txt(user, text, orig)
        return jsonify({"ok": True, "txt_path": txt_path})
    except Exception as e:
        return jsonify({"error": f"Lưu thất bại: {e}"}), 500
    
@bp.route("/pdf_to_txt", methods=["GET"])
@login_required
def page_pdf_to_txt():
    return render_template("home/pdf_to_txt.html", active="page_pdf_to_txt", current_user=session.get('user'))