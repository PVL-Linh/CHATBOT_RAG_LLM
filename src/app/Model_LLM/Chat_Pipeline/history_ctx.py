# from __future__ import annotations
# from typing import List, Dict, Any, Optional
# from app.services.history import get_history
# from app.Model_LLM.Chat_Database.redis_ctx import get_ctx

# def _get_history_msgs_for_ctx() -> List[Dict[str, str]]:
#     try:
#         hist = [
#             {"role": m["role"], "content": m["content"]}
#             for m in get_history()
#             if m["role"] in ("user", "assistant")
#         ]
#     except Exception:
#         hist = []
#     return hist

# def _get_last_assistant_message(history_msgs: List[Dict[str, str]]) -> Optional[str]:
#     for m in reversed(history_msgs or []):
#         if m.get("role") == "assistant":
#             content = (m.get("content") or "").strip()
#             if content:
#                 return content
#     return None

# def _load_ctx(session_id: str) -> Dict[str, Any]:
#     try:
#         ctx = get_ctx(session_id) or {}
#         if not isinstance(ctx, dict):
#             return {}
#         return ctx
#     except Exception:
#         return {}


from __future__ import annotations
from typing import List, Dict, Any, Optional

from flask import session

# Import từ wrapper mới
from app.services.history import (
    get_session_messages,
    get_current_session_id,
)

# Redis context vẫn theo session_id
from app.Model_LLM.Chat_Database.redis_ctx import get_ctx


def _get_history_msgs_for_ctx(session_id: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Lấy lịch sử tin nhắn (user + assistant) trong session hiện tại
    để dùng cho LLM context (follow-up detection, language detection...).
    """
    if not session_id:
        try:
            session_id = get_current_session_id()
        except Exception:
            return []

    try:
        messages = get_session_messages(session_id, limit=100)  # đủ cho context gần đây
        hist = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        return hist
    except Exception as e:
        print(f"[History CTX] Error loading messages for session {session_id}: {e}")
        return []


def _get_last_assistant_message(session_id: Optional[str] = None) -> Optional[str]:
    """Lấy tin nhắn assistant cuối cùng trong session hiện tại."""
    history_msgs = _get_history_msgs_for_ctx(session_id)
    for m in reversed(history_msgs):
        if m.get("role") == "assistant":
            content = (m.get("content") or "").strip()
            if content:
                return content
    return None


def _load_ctx(session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Load context từ Redis theo session_id.
    Nếu không có session_id → dùng session hiện tại.
    """
    if not session_id:
        try:
            session_id = get_current_session_id()
        except Exception:
            return {}

    try:
        ctx = get_ctx(session_id) or {}
        if not isinstance(ctx, dict):
            return {}
        return ctx
    except Exception as e:
        print(f"[History CTX] Error loading ctx for session {session_id}: {e}")
        return {}