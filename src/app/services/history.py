from flask import session
from app.routes.history_api import (
    MAX_HISTORY,
    read_sessions_and_messages,
    log_message,
    list_user_sessions,
    create_new_session,
    rename_session
)

__all__ = [
    "MAX_HISTORY",
    "get_history",
    "add_message",
    "read_sessions_and_messages",
    "list_user_sessions",
    "create_new_session",
    "rename_session",
]

def get_history():
    """
    Tương thích code cũ:
    Trả về danh sách message (flat) mới nhất MAX_HISTORY cho user hiện tại,
    có kèm session_id.
    """
    user = session.get("user")
    if not user:
        return []
    sessions = read_sessions_and_messages(user)
    flat = []
    for sid, msgs in sessions.items():
        for m in msgs:
            flat.append({**m, "session_id": sid})
    flat.sort(key=lambda x: x.get("ts") or "")
    return flat[-MAX_HISTORY:]

def add_message(role, content, session_id: str = ""):
    user = session.get("user")
    if not user:
        return None
    # trả lại sid để phía gọi có thể dùng tiếp
    return log_message(user, role, content, None, session_id or "")
