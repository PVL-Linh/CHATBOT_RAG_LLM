from flask import Blueprint, request, jsonify
from app.Login.login_required import login_required
from app.Helpers.Data_storage import save_item, delete_item, get_items

bp = Blueprint('saves', __name__)

@bp.route("/api/saves", methods=["GET"])
@login_required(api=True)
def api_saves():
    item_type = request.args.get("type", "fbads")
    return jsonify({"items": get_items(item_type)})

@bp.route("/api/save", methods=["POST"])
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

@bp.route("/api/saves/delete", methods=["POST"])
@login_required(api=True)
def api_delete():
    payload = request.get_json() or {}
    item_type = payload.get("type", "fbads")
    timestamp = payload.get("ts")
    if timestamp is None:
        return jsonify({"error": "Thiếu ts"}), 400
    success = delete_item(item_type, timestamp)
    return jsonify({"ok": success})