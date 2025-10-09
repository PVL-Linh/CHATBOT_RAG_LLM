import os

def _env_get(keys, default=None):
    if isinstance(keys, (list, tuple)):
        for k in keys:
            v = os.environ.get(k)
            if v is not None:
                return v
        return default
    return os.environ.get(keys, default)

def _env_bool(keys, default="0"):
    v = (_env_get(keys, default) or "").strip().lower()
    return v not in ("0", "false", "no", "")

def _env_int(keys, default="0"):
    try:
        return int(_env_get(keys, default))
    except:
        return int(default)

def _env_float(keys, default="0.0"):
    try:
        return float(_env_get(keys, default))
    except:
        return float(default)

def _resolve_path(p: str) -> str:
    if not p:
        return p
    if os.path.isabs(p):
        return p
    return os.path.abspath(os.path.join(os.getcwd(), p))
