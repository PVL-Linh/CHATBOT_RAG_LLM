# -*- coding: utf-8 -*-
# Marketing_Planner/helpers_resolve.py
import re
from .channels_store import get_by_id, get_by_name

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

def resolve_channel(raw: str):
    raw = (raw or "").strip()
    if UUID_RE.match(raw):
        return get_by_id(raw)
    return get_by_name(raw)
