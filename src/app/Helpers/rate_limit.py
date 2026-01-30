import os, time, threading
from collections import deque
from dataclasses import dataclass

@dataclass
class Limits:
    rpm: int
    tpm: int
    max_queue_s: int

class TokenRPMShaper:
    """
    Leaky-bucket cho RPM/TPM + AIMD để tự điều chỉnh khi gặp 429.
    Dùng chung cho cả text & image.
    """
    def __init__(self, limits: Limits, name="default"):
        self.limits = limits
        self.name = name
        self._req = deque()
        self._tok = deque()
        self._lock = threading.Lock()
        self._aimd_k = 1.0

    def _gc(self):
        now = time.time()
        while self._req and now - self._req[0] > 60: self._req.popleft()
        while self._tok and now - self._tok[0][0] > 60: self._tok.popleft()

    def _window(self):
        self._gc()
        return len(self._req), sum(t for _, t in self._tok)

    def acquire(self, add_tokens: int):
        deadline = time.time() + self.limits.max_queue_s
        with self._lock:
            while True:
                now = time.time()
                if now > deadline:
                    raise TimeoutError(f"{self.name} queue timeout")
                used_rpm, used_tpm = self._window()
                rpm_cap = max(1, int(self.limits.rpm * self._aimd_k))
                if used_rpm < rpm_cap and (used_tpm + add_tokens) <= self.limits.tpm:
                    self._req.append(now)
                    self._tok.append((now, add_tokens))
                    return
                time.sleep(0.25)

    def on_429(self):
        with self._lock:
            self._aimd_k = max(0.25, self._aimd_k * 0.5)

    def on_success(self):
        with self._lock:
            self._aimd_k = min(1.0, self._aimd_k + 0.05)

_text_limiter = None
_img_limiter  = None

def _limits_from_env(prefix, rpm_def, tpm_def, wait_def):
    rpm  = int(os.getenv(f"{prefix}_RPM", rpm_def))
    tpm  = int(os.getenv(f"{prefix}_TPM", tpm_def))
    wait = int(os.getenv(f"{prefix}_MAX_QUEUE_S", wait_def))
    return Limits(rpm, tpm, wait)

def get_text_limiter():
    global _text_limiter
    if _text_limiter is None:
        lim = _limits_from_env("AI_STUDIO_TEXT", 60, 200_000, 20)
        _text_limiter = TokenRPMShaper(lim, name="text")
    return _text_limiter

def get_img_limiter():
    global _img_limiter
    if _img_limiter is None:
        lim = _limits_from_env("AI_STUDIO_IMG", 12, 80_000, 45)
        _img_limiter = TokenRPMShaper(lim, name="image")
    return _img_limiter
