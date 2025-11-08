# redis_cache.py
from __future__ import annotations
import json
from typing import Any, Optional
from app.config.config_supabase import REDIS_URL, CACHE_TTL_SECONDS

try:
    import redis  # type: ignore
except Exception:
    redis = None

_rds = None
if redis is not None:
    try:
        _rds = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        _rds.ping()
    except Exception:
        _rds = None

def available() -> bool:
    return _rds is not None

def get_json(key: str) -> Optional[Any]:
    if not _rds: return None
    try:
        raw = _rds.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None

def set_json(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    if not _rds: return
    try:
        _rds.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass

def key_for(*parts: str) -> str:
    return "tiximax:" + ":".join([p.strip() for p in parts if p and p.strip()])
