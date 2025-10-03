# Helpers/channels_store.py
# -*- coding: utf-8 -*-
import json, os, uuid
from typing import List, Dict, Any

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Data_app")
CHANNELS_FILE = os.path.join(DATA_DIR, "channels.json")

# Danh sách mặc định để seed lần đầu
SEED_CHANNELS = [
    {"name": "Facebook",      "platform": "Social Media"},
    {"name": "TikTok",        "platform": "Video Sharing"},
    {"name": "Instagram",     "platform": "Social Media"},
    {"name": "Blog Website",  "platform": "Blog/Website"},
    {"name": "Zalo OA",       "platform": "Messaging"},
    {"name": "YouTube",       "platform": "Video Sharing"},
    {"name": "LinkedIn",      "platform": "Professional"},
]

# Map đoán structure khi không cung cấp
_STRUCTURE_GUESS = {
    "tiktok": "tiktok_script",
    "facebook": "facebook_post",
    "fanpage": "facebook_post",
    "instagram": "instagram_post",
    "reels": "instagram_post",
    "blog": "blog_longform",
    "website": "blog_longform",
    "seo": "blog_longform",
    "youtube": "youtube_script",
    "shorts": "youtube_script",
    "linkedin": "linkedin_post",
    "zalo": "zalo_oa_post",
    "official account": "zalo_oa_post",
}

# ---------------- I/O cơ bản ----------------
def _ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    # Nếu chưa có file → tạo file rỗng
    if not os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    # Nếu file trống → seed kênh mặc định như bản ghi thường (UUID)
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        data = []
    if not data:
        seeded = []
        for s in SEED_CHANNELS:
            seeded.append({
                "id": str(uuid.uuid4()),
                "name": s["name"],
                "platform": s.get("platform") or "Social Media",
                "audience": "",
                "tone": "",
                "visual_guide": "",
                "formats": "",
                "length": "",
                "hashtags": "",
                "cta": "",
                "risk_notes": "",
                "special": "",
                "content_guide": "",
                "structure": "blog_longform",
                "system_prompt_override": "",
            })
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(seeded, f, ensure_ascii=False, indent=2)

def load_channels() -> List[Dict[str, Any]]:
    _ensure_file()
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_channels(items: List[Dict[str, Any]]):
    _ensure_file()
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

# -------------- Helpers chuẩn hoá/upsert --------------
def _guess_structure(item: Dict[str, Any]) -> str:
    s = (item.get("structure") or "").strip().lower()
    if s:
        return s
    name = (item.get("name") or "").strip().lower()
    platform = (item.get("platform") or "").strip().lower()
    for key in (name, platform):
        for kw, st in _STRUCTURE_GUESS.items():
            if kw in key:
                return st
    return "blog_longform"

def _normalize_channel(item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item)
    # id: nếu có thì giữ, nếu không có mà có name -> dùng name làm id tạm; nếu vẫn trống -> gen UUID
    cid = (out.get("id") or "").strip()
    cname = (out.get("name") or "").strip()
    if not cid:
        cid = cname if cname else str(uuid.uuid4())
    out["id"] = cid
    out["name"] = cname
    out["platform"] = (out.get("platform") or "Social Media").strip()
    out["structure"] = _guess_structure(out)

    # Các field text -> string, tránh None
    for k in (
        "audience", "tone", "content_guide", "visual_guide", "formats",
        "length", "hashtags", "cta", "risk_notes", "special", "system_prompt_override"
    ):
        v = out.get(k)
        out[k] = ("" if v is None else str(v)).strip()

    return out

def upsert_channels_from_json(payload) -> Dict[str, Any]:
    """
    Upsert danh sách channel từ JSON array (hoặc chuỗi JSON).
    - Ưu tiên trùng 'id' (không phân biệt hoa thường).
    - Nếu không có 'id', dùng 'name' (case-insensitive).
    """
    import json as _json
    items = load_channels()

    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            return {"error": "Payload không phải là JSON hợp lệ."}

    if not isinstance(payload, list):
        return {"error": "Payload phải là JSON array các channel objects."}

    # Lập index hiện có
    by_id = {}
    by_name = {}
    for i, c in enumerate(items):
        cid = (c.get("id") or "").strip()
        cname = (c.get("name") or "").strip().lower()
        if cid:
            by_id[cid] = i
        if cname:
            by_name[cname] = i

    inserted = 0
    updated = 0
    skipped = 0
    details: List[Dict[str, Any]] = []

    for raw in payload:
        if not isinstance(raw, dict):
            skipped += 1
            details.append({"status": "skip:not_object"})
            continue

        norm = _normalize_channel(raw)
        cid = norm["id"].strip()
        cname = norm["name"].strip()
        if not cname:
            skipped += 1
            details.append({"status": "skip:missing_name", "id": cid})
            continue

        idx = None
        if cid and cid in by_id:
            idx = by_id[cid]
        elif cname.lower() in by_name:
            idx = by_name[cname.lower()]

        if idx is None:
            items.append(norm)
            new_index = len(items) - 1
            if cid: by_id[cid] = new_index
            by_name[cname.lower()] = new_index
            inserted += 1
            details.append({"name": cname, "status": "inserted"})
        else:
            # merge update
            items[idx].update(norm)
            updated += 1
            details.append({"name": cname, "status": "updated"})

    save_channels(items)
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": len(items),
        "details": details
    }

def import_from_json_file(file_path: str) -> Dict[str, Any]:
    """Import trực tiếp từ file JSON (array) trên đĩa."""
    if not os.path.exists(file_path):
        return {"error": f"File không tồn tại: {file_path}"}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        return {"error": f"Không đọc được file JSON: {e}"}
    return upsert_channels_from_json(payload)

# -------------- CRUD lẻ --------------
def create_channel(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_channels()
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("Channel name is required")
    new_item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "platform": payload.get("platform") or "Social Media",
        "audience": payload.get("audience") or "",
        "tone": payload.get("tone") or "",
        "content_guide": payload.get("content_guide") or "",
        "visual_guide": payload.get("visual_guide") or "",
        "formats": payload.get("formats") or "",
        "length": payload.get("length") or "",
        "hashtags": payload.get("hashtags") or "",
        "cta": payload.get("cta") or "",
        "risk_notes": payload.get("risk_notes") or "",
        "special": payload.get("special") or "",
        "structure": payload.get("structure") or "blog_longform",
        "system_prompt_override": payload.get("system_prompt_override") or "",
    }
    items.append(new_item)
    save_channels(items)
    return new_item

def update_channel(cid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_channels()
    for it in items:
        if it["id"] == cid:
            for k in [
                "name","platform","audience","tone","content_guide","visual_guide",
                "formats","length","hashtags","cta","risk_notes","special",
                "structure","system_prompt_override"
            ]:
                if k in payload:
                    it[k] = payload[k] if payload[k] is not None else ""
            save_channels(items)
            return it
    raise KeyError("Channel not found")

def delete_channel(cid: str):
    items = load_channels()
    new_items = [x for x in items if x["id"] != cid]
    if len(new_items) == len(items):
        raise KeyError("Channel not found")
    save_channels(new_items)

# -------------- Trợ giúp cho planner --------------
def list_all_for_planner() -> List[Dict[str, Any]]:
    # Chỉ đọc từ JSON — tất cả đều sửa/xoá được
    return load_channels()

def get_by_name(name: str) -> Dict[str, Any] | None:
    if not name: return None
    for it in load_channels():
        if it["name"].strip().lower() == name.strip().lower():
            return it
    return None

def get_by_id(cid: str) -> Dict[str, Any] | None:
    if not cid: return None
    for it in load_channels():
        if it.get("id") == cid:
            return it
    return None
