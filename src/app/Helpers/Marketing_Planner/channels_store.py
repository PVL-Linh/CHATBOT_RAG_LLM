# Helpers/channels_store.py
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
    }
    items.append(new_item)
    save_channels(items)
    return new_item

def update_channel(cid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_channels()
    for it in items:
        if it["id"] == cid:
            for k in ["name","platform","audience","tone","content_guide","visual_guide",  # <-- thêm content_guide
                        "formats","length","hashtags","cta","risk_notes","special"]:
                if k in payload:
                    it[k] = payload[k]
            save_channels(items)
            return it
    raise KeyError("Channel not found")

def delete_channel(cid: str):
    items = load_channels()
    new_items = [x for x in items if x["id"] != cid]
    if len(new_items) == len(items):
        raise KeyError("Channel not found")
    save_channels(new_items)

def list_all_for_planner() -> List[Dict[str, Any]]:
    # Chỉ đọc từ JSON — tất cả đều sửa/xoá được
    return load_channels()

def get_by_name(name: str) -> Dict[str, Any] | None:
    if not name: return None
    for it in load_channels():
        if it["name"].strip().lower() == name.strip().lower():
            return it
    return None
