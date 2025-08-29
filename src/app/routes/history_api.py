from flask import Blueprint, jsonify, request, session
from app.Login.login_required import login_required
from app.services.history import read_sessions_and_messages, get_history, MAX_HISTORY

bp = Blueprint("history_api", __name__)

@bp.route("/api/history", methods=["GET"])
@login_required(api=True)
def api_history():
    user = session.get("user")
    if not user:
        return jsonify({"items": []})
    limit = int(request.args.get("limit", 50))
    sessions = read_sessions_and_messages(user)

    flat = []
    for sid, msgs in sessions.items():
        for m in msgs:
            flat.append({**m, "session_id": sid})
    flat.sort(key=lambda x: x.get("ts") or "")

    return jsonify({"items": flat[-min(limit, MAX_HISTORY):]})

@bp.route("/api/history/sessions", methods=["GET"])
@login_required(api=True)
def api_history_sessions():
    user = session.get("user")
    if not user:
        return jsonify({"sessions": []})
    sessions = read_sessions_and_messages(user)

    out = []
    for sid, msgs in sessions.items():
        if not msgs:
            continue
        first_user = next((m for m in msgs if m.get("role") == "user"), None)
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

@bp.route("/api/history/by_session", methods=["GET"])
@login_required(api=True)
def api_history_by_session():
    user = session.get("user")
    if not user:
        return jsonify({"items": []})
    sid = (request.args.get("session_id") or "").strip() or "default"
    sessions = read_sessions_and_messages(user)
    items = sessions.get(sid, [])
    return jsonify({"items": items})
