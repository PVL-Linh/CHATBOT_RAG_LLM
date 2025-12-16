# app/Model_LLM/Chat_Database/redis_ctx.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import time
import threading
import fnmatch
from typing import Any, Dict, Optional, List

import redis

# ============================================================
# 1. CẤU HÌNH & FALLBACK DictRedis
# ============================================================

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_TTL = int(os.environ.get("REDIS_CTX_TTL", "1800"))  # 30 phút

class DictRedis:
    """
    Fallback Redis đơn giản dùng in-memory dictionary.
    Dùng cho môi trường dev / khi Redis Docker không chạy.

    Hỗ trợ:
    - get(key)
    - set(key, value, ex=None)
    - setex(key, ttl, value)
    - delete(*keys)
    - keys(pattern)
    - ping()
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _cleanup(self) -> None:
        """Xoá các key đã hết hạn."""
        now = time.time()
        expired: List[str] = []
        for k, ts in list(self._expiry.items()):
            if ts <= now:
                expired.append(k)
        for k in expired:
            self._store.pop(k, None)
            self._expiry.pop(k, None)

    # ------------------------------
    # API mô phỏng redis-py
    # ------------------------------
    def get(self, key: str) -> Optional[str]:
        with self._lock:
            self._cleanup()
            val = self._store.get(key)
            if val is None:
                return None
            # Giả lập decode_responses=True -> trả về str
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val)

    def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
        keepttl: bool = False,
        get: bool = False,
    ) -> bool:
        """
        Hỗ trợ các tham số thường dùng của redis.set:
        - ex: TTL giây
        - px, nx, xx, keepttl, get: bỏ qua, chỉ để tương thích chữ ký hàm.
        """
        with self._lock:
            self._cleanup()

            # Xử lý nx/xx đơn giản:
            if nx and key in self._store:
                return False
            if xx and key not in self._store:
                return False

            # Lưu giá trị
            self._store[key] = value

            # TTL
            ttl_seconds: Optional[float] = None
            if ex is not None:
                ttl_seconds = float(ex)
            elif px is not None:
                ttl_seconds = float(px) / 1000.0

            if ttl_seconds is not None and not keepttl:
                self._expiry[key] = time.time() + ttl_seconds
            elif not keepttl:
                # Không TTL mới → bỏ expiry cũ nếu có
                self._expiry.pop(key, None)

            # get=True theo spec sẽ trả về giá trị cũ, nhưng
            # để đơn giản dev: bỏ qua, cứ trả True.
            return True

    def setex(self, key: str, ttl: int, value: Any) -> bool:
        with self._lock:
            self._cleanup()
            self._store[key] = value
            self._expiry[key] = time.time() + int(ttl)
            return True

    def delete(self, *keys: str) -> int:
        removed = 0
        with self._lock:
            self._cleanup()
            for k in keys:
                if k in self._store:
                    removed += 1
                    self._store.pop(k, None)
                self._expiry.pop(k, None)
        return removed

    def keys(self, pattern: str = "*") -> List[str]:
        with self._lock:
            self._cleanup()
            return [k for k in self._store.keys() if fnmatch.fnmatch(k, pattern)]

    def ping(self) -> bool:
        return True


def _init_client():
    """
    Thử kết nối Redis thật.
    Nếu fail thì fallback sang DictRedis in-memory.
    """
    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        print(f"[redis_ctx] Connected to Redis at {REDIS_URL}")
        return client
    except Exception as e:
        print(f"[redis_ctx] Redis unavailable, fallback to in-memory DictRedis: {e}")
        return DictRedis()


# CLIENT TOÀN CỤC – TỰ ĐỘNG CHỌN REDIS HOẶC DICTREDIS
redis_client = _init_client()


def _client():
    return redis_client


# ============================================================
# 2. HÀM LÀM VIỆC VỚI CTX SESSION
# ============================================================

def _k(session_id: str) -> str:
    """Tạo key lưu context theo session_id."""
    return f"ctx:{session_id}"


def get_ctx(session_id: str) -> Dict[str, Any]:
    """Lấy context (dict) từ Redis/DictRedis."""
    if not session_id:
        return {}
    raw = _client().get(_k(session_id))
    if not raw:
        return {}
    try:
        # THÊM: xử lý trường hợp raw là list (lỗi cũ khi lưu history sai)
        if isinstance(raw, list):
            print(f"[redis_ctx] WARNING: ctx raw là list thay vì dict cho session {session_id}. Reset ctx.")
            return {}
        
        # Bình thường: raw là str (JSON) hoặc dict
        if isinstance(raw, dict):
            return raw
        return json.loads(raw)
    except Exception as e:
        print(f"[redis_ctx] Parse ctx error for {session_id}: {e}")
        return {}

def set_ctx(session_id: str, data: Dict[str, Any]) -> None:
    """Ghi context (dict) vào Redis/DictRedis với TTL."""
    if not session_id:
        return
    payload = json.dumps(data or {}, ensure_ascii=False)
    # Redis thật + DictRedis đều hỗ trợ setex
    _client().setex(_k(session_id), DEFAULT_TTL, payload)


def clear_ctx(session_id: str) -> None:
    """Xoá context của session."""
    if not session_id:
        return
    _client().delete(_k(session_id))


def update_ctx(session_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge patch vào ctx hiện tại và lưu lại."""
    cur = get_ctx(session_id)
    cur.update(patch or {})
    set_ctx(session_id, cur)
    return cur


# ============================================================
# 3. CÁC HÀM TIỆN ÍCH 'NHỚ' THÔNG TIN
# ============================================================

def remember_time_window(session_id: str, lo: str, hi: str) -> None:
    """
    Nhớ lại khoảng thời gian truy vấn gần nhất
    lo, hi: string ISO date hoặc bất kỳ format bạn đang dùng.
    """
    update_ctx(
        session_id,
        {
            "last_time_window": {
                "lo": lo,
                "hi": hi,
                "ts": int(time.time()),
            }
        },
    )


def remember_order_code(session_id: str, code: str) -> None:
    """Nhớ mã đơn hàng gần nhất mà user hỏi."""
    update_ctx(session_id, {"last_order_code": code})


def remember_intent(session_id: str, intent: str, confidence: float) -> None:
    """Nhớ intent phân loại gần nhất."""
    update_ctx(
        session_id,
        {
            "last_intent": {
                "name": intent,
                "conf": round(float(confidence), 3),
            }
        },
    )
