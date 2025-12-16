from __future__ import annotations
from typing import List, Dict, Any
from flask import session
import uuid

# Import từ history_api Supabase version
from app.routes.history_api import (
    log_message,
    get_session_messages,
    list_user_sessions,
    create_new_session,
    rename_session,
)

__all__ = [
    "get_recent_history",
    "get_session_messages",
    "add_message",
    "get_sessions_list",
    "create_new_session",
    "rename_session",
    "get_current_session_id",
]


def get_current_session_id() -> str:
    """
    Lấy session_id hiện tại (mới nhất) hoặc tạo mới nếu chưa có.
    """
    sessions = get_sessions_list()
    if sessions:
        return sessions[0]["id"]  # đã được sort theo updated_at DESC

    # Tạo session mới nếu chưa có
    info = create_new_session(title="Cuộc trò chuyện mới")
    return info["session_id"]


def get_sessions_list() -> List[Dict[str, Any]]:
    """Lấy danh sách tất cả session của user hiện tại."""
    user = session.get("user")
    if not user:
        return []
    return list_user_sessions()


def get_session_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0
) -> list[dict]:
    """
    Lấy tin nhắn của một session cụ thể, hỗ trợ phân trang.
    """
    from app.routes.history_api import get_session_messages as _api_get_msgs
    return _api_get_msgs(session_id, limit=limit, offset=offset)


def get_recent_history(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Tương thích code cũ nếu nơi nào còn dùng get_history().
    Lấy tin nhắn mới nhất từ tất cả session (global recent).
    """
    sessions = get_sessions_list()
    if not sessions:
        return []

    all_msgs = []
    for sess in sessions[:10]:  # chỉ lấy 10 session mới nhất để tránh load quá nhiều
        msgs = get_session_messages(sess["id"], limit=limit * 2)
        for m in msgs:
            m["session_id"] = sess["id"]
            all_msgs.append(m)

    all_msgs.sort(key=lambda x: x.get("ts_utc") or "1970-01-01T00:00:00Z")
    return all_msgs[-limit:]


def add_message(
    role: str,
    content: str,
    session_id: str | None = None,
    model: str | None = None,
    metadata: dict | None = None,
) -> str:

    if not session.get("user"):
        raise ValueError("User not authenticated")

    return log_message(
        role=role,
        content=content,
        session_id=session_id,
        model=model,
        metadata=metadata,
    )


def validate_and_fix_session_id(session_id: str | None) -> str:
    """
    Kiểm tra session_id có phải UUID hợp lệ không.
    Nếu sai → tạo mới.
    """
    if not session_id:
        return str(uuid.uuid4())
    
    try:
        uuid.UUID(session_id)
        return session_id
    except ValueError:
        print(f"[Warning] Session ID không hợp lệ: '{session_id}' → tạo mới")
        return str(uuid.uuid4())