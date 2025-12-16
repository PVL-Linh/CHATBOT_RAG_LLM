# from flask import session
# from app.routes.history_api import (
#     MAX_HISTORY,
#     read_sessions_and_messages,
#     log_message,
#     list_user_sessions,
#     create_new_session,
#     rename_session
# )

# __all__ = [
#     "MAX_HISTORY",
#     "get_history",
#     "add_message",
#     "read_sessions_and_messages",
#     "list_user_sessions",
#     "create_new_session",
#     "rename_session",
# ]

# def get_history():
#     """
#     Tương thích code cũ:
#     Trả về danh sách message (flat) mới nhất MAX_HISTORY cho user hiện tại,
#     có kèm session_id.
#     """
#     user = session.get("user")
#     if not user:
#         return []
#     sessions = read_sessions_and_messages(user)
#     flat = []
#     for sid, msgs in sessions.items():
#         for m in msgs:
#             flat.append({**m, "session_id": sid})
#     flat.sort(key=lambda x: x.get("ts") or "")
#     return flat[-MAX_HISTORY:]

# def add_message(role, content, session_id: str = ""):
#     user = session.get("user")
#     if not user:
#         return None
#     return log_message(user, role, content, None, session_id or "")


# app/history/wrapper.py

from flask import session
from app.routes.history_api import (
    MAX_HISTORY,
    log_message,
    list_user_sessions,
    create_new_session,
    rename_session,
    get_session_messages,
)

__all__ = [
    "MAX_HISTORY",
    "get_recent_history",
    "get_session_messages",
    "add_message",
    "get_sessions_list",
    "create_new_session",
    "rename_session",
    "get_current_session_id",
]

# ===================================================================
# 1. Tương thích code cũ (nếu bạn vẫn gọi get_history() ở đâu đó)
# ===================================================================
def get_recent_history(limit: int | None = None) -> list[dict]:
    """
    Tương thích với code cũ: trả về tin nhắn mới nhất toàn user (global recent).
    Giới hạn bởi limit hoặc MAX_HISTORY.
    """
    user = session.get("user")
    if not user:
        return []

    limit = min(limit or MAX_HISTORY, MAX_HISTORY)

    # Lấy tất cả session
    sessions = get_sessions_list()
    if not sessions:
        return []

    all_messages = []
    for sess in sessions:
        msgs = get_session_messages(sess["id"], limit=limit * 2)  # lấy dư một chút để sort
        for msg in msgs:
            msg["session_id"] = sess["id"]
            all_messages.append(msg)

    # Sort theo thời gian và lấy mới nhất
    all_messages.sort(key=lambda x: x.get("ts_utc") or "")
    recent = all_messages[-limit:]

    return recent


# ===================================================================
# 2. Hàm chính - KHUYẾN NGHỊ DÙNG TRONG FRONTEND CHAT
# ===================================================================
def get_session_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0
) -> list[dict]:
    """
    Lấy tin nhắn của một session cụ thể, hỗ trợ phân trang.
    Đây là hàm bạn nên dùng chính trong logic chat.
    """
    from app.routes.history_api import get_session_messages as api_get_msgs
    return api_get_msgs(session_id, limit=limit, offset=offset)


def add_message(
    role: str,
    content: str,
    session_id: str | None = None,
    model: str | None = None,
    metadata: dict | None = None
) -> str | None:
    """
    Thêm tin nhắn mới.
    Trả về session_id thực tế đã sử dụng (rất hữu ích cho frontend).
    """
    user = session.get("user")
    if not user:
        return None

    try:
        return log_message(
            role=role,
            content=content,
            session_id=session_id,
            model=model,
            metadata=metadata
        )
    except Exception as e:
        print(f"Error adding message: {e}")
        return None


# ===================================================================
# 3. Các hàm tiện ích khác
# ===================================================================
def get_sessions_list() -> list[dict]:
    """Trả về danh sách tất cả session của user hiện tại (có preview, count...)"""
    user = session.get("user")
    if not user:
        return []
    return list_user_sessions()


def get_current_session_id() -> str:
    """
    Lấy session đang active (mới nhất) hoặc tạo mới nếu chưa có.
    Rất tiện khi khởi tạo trang chat.
    """
    sessions = get_sessions_list()
    if sessions:
        return sessions[0]["id"]

    info = create_new_session()
    return info["session_id"]