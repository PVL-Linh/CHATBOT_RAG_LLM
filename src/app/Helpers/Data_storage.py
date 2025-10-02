import os
import json
from typing import Dict, List, Any
import time
# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SAVED_PATH = os.path.join(DATA_DIR, "saved.json")

def ensure_store() -> None:
    """Ensure data directory and saved.json file exist"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SAVED_PATH):
        with open(SAVED_PATH, "w", encoding="utf-8") as f:
            json.dump({"fbads": [], "rephrase": [], "tiktok": [], "fab": []}, f, ensure_ascii=False, indent=2)

def load_saves() -> Dict[str, List[Any]]:
    """Load saved data from JSON file"""
    ensure_store()
    with open(SAVED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_saves(data: Dict[str, List[Any]]) -> None:
    """Save data to JSON file"""
    with open(SAVED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_item(item_type: str, text: str, input_data: Dict = None, meta: Dict = None) -> Dict[str, Any]:
    """Save a single item to storage"""

    
    item = {
        "ts": int(time.time()),
        "text": text,
        "input": input_data or {},
        "meta": meta or {}
    }
    
    data = load_saves()
    data.setdefault(item_type, [])
    data[item_type].insert(0, item)
    save_saves(data)
    
    return item

def delete_item(item_type: str, timestamp: int) -> bool:
    """Delete an item by timestamp"""
    data = load_saves()
    data.setdefault(item_type, [])
    
    original_count = len(data[item_type])
    data[item_type] = [x for x in data[item_type] if x.get("ts") != timestamp]
    save_saves(data)
    
    return len(data[item_type]) < original_count

def get_items(item_type: str) -> List[Dict[str, Any]]:
    """Get all items of a specific type"""
    return load_saves().get(item_type, [])