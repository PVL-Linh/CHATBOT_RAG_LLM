# -*- coding: utf-8 -*-
# app/rag_hr/service.py
from __future__ import annotations
from .repo import create_session, get_session_owner

class SessionOwnershipError(PermissionError):
    pass

def ensure_valid_or_create_session(session_id: str, user: str, title: str) -> str:
    """
    - Không có session_id  -> tạo mới.
    - Có session_id nhưng không tồn tại -> tạo mới.
    - Có session_id của user khác -> raise SessionOwnershipError.
    - Có session_id đúng user -> dùng lại.
    """
    if not session_id:
        return create_session(user=user, title=title)
    owner = get_session_owner(session_id)
    if owner is None:
        return create_session(user=user, title=title)
    if owner != user:
        raise SessionOwnershipError("Forbidden: session does not belong to current user")
    return session_id
