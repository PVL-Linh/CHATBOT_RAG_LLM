from __future__ import annotations
from flask import Blueprint, request, jsonify
from app.Login.login_required import build_principal_from_session
from .chat_engine import handle_chat_request

bp = Blueprint("WAREHOUSE", __name__)

@bp.route("/api/WAREHOUSE", methods=["POST"])
def chat_api():
    data = request.get_json(force=True) or {}
    user_text = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    principal = build_principal_from_session()

    result = handle_chat_request(
        user_text=user_text,
        session_id=session_id,
        principal=principal,
    )

    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@bp.route("/chat", methods=["POST"])
def chat_api_alias():
    return chat_api()