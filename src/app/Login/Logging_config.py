import os, csv
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from pathlib import Path


CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/app/Data_app/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _log_message_to_csv(username: str, role: str, content: str, ts_utc_iso: str, session_id: str = ""):
    if not username:
        return
    _ensure_dir(CHAT_LOGS_DIR)
    filepath = os.path.join(CHAT_LOGS_DIR, f"{username}.csv")

    try:
        local_tz = ZoneInfo(LOCAL_TZ_NAME)
    except Exception:
        local_tz = timezone.utc

    try:
        ts_utc = datetime.fromisoformat(ts_utc_iso.replace('Z', '+00:00'))
    except Exception:
        ts_utc = datetime.now(timezone.utc)
        ts_utc_iso = ts_utc.isoformat()

    ts_local_iso = ts_utc.astimezone(local_tz).isoformat()

    file_exists = os.path.exists(filepath)
    with open(filepath, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # bổ sung cột session_id
        if not file_exists:
            writer.writerow(['ts_utc', 'ts_local', 'username', 'session_id', 'role', 'content'])
        writer.writerow([ts_utc_iso, ts_local_iso, username, session_id or "", role, content])

# --- Đọc theo session (public API cho routes) ---
def read_sessions_and_messages(username: str):
    """
    Trả về dict[session_id] -> list[{role, content, ts}]
    Ưu tiên đọc JSON {username}.json; nếu chưa có thì đọc CSV {username}.csv.
    """
    from pathlib import Path
    import csv, json

    _ensure_dir(CHAT_LOGS_DIR)
    p_json = Path(CHAT_LOGS_DIR) / f"{username}.json"
    p_csv  = Path(CHAT_LOGS_DIR) / f"{username}.csv"

    sessions = {}

    # 1) Thử JSON trước
    if p_json.exists():
        try:
            with p_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # dữ liệu là list các message
            for item in (data if isinstance(data, list) else []):
                sid = (item.get("session_id") or "").strip() or "default"
                role = (item.get("role") or "").strip()
                content = item.get("content") or ""
                ts = (item.get("ts_utc") or item.get("ts_local") or "").strip()
                if not content:
                    continue
                sessions.setdefault(sid, []).append({"role": role, "content": content, "ts": ts})
        except Exception:
            sessions = {}

    # 2) Nếu JSON không có/đọc lỗi và CSV tồn tại -> fallback CSV
    if not sessions and p_csv.exists():
        try:
            with p_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                has_sid = 'session_id' in (reader.fieldnames or [])
                for r in reader:
                    sid = (r.get('session_id') or "").strip() if has_sid else "default"
                    role = (r.get('role') or "").strip()
                    content = r.get('content') or ""
                    ts = (r.get('ts_utc') or r.get('ts_local') or "").strip()
                    if not content:
                        continue
                    sessions.setdefault(sid, []).append({"role": role, "content": content, "ts": ts})
        except Exception:
            sessions = {}

    # Sắp xếp theo thời gian trong từng session
    for sid in sessions:
        sessions[sid].sort(key=lambda x: x.get("ts") or "")

    return sessions
