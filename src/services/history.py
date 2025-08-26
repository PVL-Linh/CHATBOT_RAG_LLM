import os, csv
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from flask import session, current_app as app

MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "50"))
CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
    
def _log_message_to_csv_sid(username: str, role: str, content: str, ts_utc_iso: str, session_id: str = ""):
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
        if not file_exists:
            writer.writerow(['ts_utc', 'ts_local', 'username', 'session_id', 'role', 'content'])
        writer.writerow([ts_utc_iso, ts_local_iso, username, session_id or "", role, content])

def get_history():
    msgs = session.get("messages") or []
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
        session["messages"] = msgs
    return msgs

def add_message(role, content, session_id: str = ""):
    msgs = get_history()
    ts_utc_iso = datetime.now(timezone.utc).isoformat()
    msgs.append({"role": role, "content": content, "ts": ts_utc_iso, "session_id": session_id or ""})
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
    session["messages"] = msgs
    try:
        _log_message_to_csv_sid(session.get('user'), role, content, ts_utc_iso, session_id or "")
    except Exception as e:
        try:
            app.logger.exception("Failed to write chat CSV: %s", e)
        except Exception:
            pass

def read_sessions_and_messages(username: str):
    p = Path(CHAT_LOGS_DIR) / f"{username}.csv"
    sessions = {}
    if not p.exists():
        return sessions
    
    with p.open("r", encoding="utf-8", newline="") as f:
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
    for sid in sessions:
        sessions[sid].sort(key=lambda x: x.get("ts") or "")
    return sessions