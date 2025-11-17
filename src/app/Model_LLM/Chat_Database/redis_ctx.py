# app/services/redis_ctx.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time
from typing import Any, Dict, Optional
import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

def _client() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)

def _k(session_id: str) -> str:
    return f"tiximax:chatctx:{session_id}"

DEFAULT_TTL = int(os.environ.get("REDIS_CHATCTX_TTL", "86400"))  # 1 ngày

def get_ctx(session_id: str) -> Dict[str, Any]:
    if not session_id: return {}
    r = _client()
    raw = r.get(_k(session_id))
    return json.loads(raw) if raw else {}

def set_ctx(session_id: str, data: Dict[str, Any]) -> None:
    if not session_id: return
    r = _client()
    r.setex(_k(session_id), DEFAULT_TTL, json.dumps(data or {}))

def update_ctx(session_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = get_ctx(session_id)
    cur.update(patch or {})
    set_ctx(session_id, cur)
    return cur

def remember_time_window(session_id: str, lo: str, hi: str) -> None:
    update_ctx(session_id, {"last_time_window": {"lo": lo, "hi": hi, "ts": int(time.time())}})

def remember_order_code(session_id: str, code: str) -> None:
    update_ctx(session_id, {"last_order_code": code})

def remember_intent(session_id: str, intent: str, confidence: float) -> None:
    update_ctx(session_id, {"last_intent": {"name": intent, "conf": round(confidence, 3)}})
