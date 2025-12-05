from __future__ import annotations
from typing import List, Dict, Any, Optional
from app.services.history import get_history
from app.Model_LLM.Chat_Database.redis_ctx import get_ctx

def _get_history_msgs_for_ctx() -> List[Dict[str, str]]:
    try:
        hist = [
            {"role": m["role"], "content": m["content"]}
            for m in get_history()
            if m["role"] in ("user", "assistant")
        ]
    except Exception:
        hist = []
    return hist

def _get_last_assistant_message(history_msgs: List[Dict[str, str]]) -> Optional[str]:
    for m in reversed(history_msgs or []):
        if m.get("role") == "assistant":
            content = (m.get("content") or "").strip()
            if content:
                return content
    return None

def _load_ctx(session_id: str) -> Dict[str, Any]:
    try:
        ctx = get_ctx(session_id) or {}
        if not isinstance(ctx, dict):
            return {}
        return ctx
    except Exception:
        return {}
