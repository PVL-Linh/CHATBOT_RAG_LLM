import os, csv
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from pathlib import Path


CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

# def _ensure_dir(path: str):
#     os.makedirs(path, exist_ok=True)

# def _log_message_to_csv(username: str, role: str, content: str, ts_utc_iso: str):
#     if not username:
#         return
#     _ensure_dir(CHAT_LOGS_DIR)
#     filepath = os.path.join(CHAT_LOGS_DIR, f"{username}.csv")

#     try:
#         local_tz = ZoneInfo(LOCAL_TZ_NAME)
#     except Exception:
#         local_tz = timezone.utc

#     try:
#         ts_utc = datetime.fromisoformat(ts_utc_iso.replace('Z', '+00:00'))
#     except Exception:
#         ts_utc = datetime.now(timezone.utc)
#         ts_utc_iso = ts_utc.isoformat()

#     ts_local_iso = ts_utc.astimezone(local_tz).isoformat()

#     file_exists = os.path.exists(filepath)
#     with open(filepath, 'a', newline='', encoding='utf-8') as f:
#         writer = csv.writer(f)
#         if not file_exists:
#             writer.writerow(['ts_utc', 'ts_local', 'username', 'role', 'content'])
#         writer.writerow([ts_utc_iso, ts_local_iso, username, role, content])


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

def _read_sessions_and_messages(username: str):
    """
    Trả về:
      sessions: dict[session_id] -> list[ {role, content, ts} ] (đã sort theo ts tăng dần)
    Nếu file cũ không có cột session_id, đưa về session_id = "default".
    """
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

    # sort từng session theo ts
    for sid in sessions:
        sessions[sid].sort(key=lambda x: x.get("ts") or "")
    return sessions
# def _read_persistent_history(username: str, limit: int = 200):
#     """
#     Đọc chat_logs/<username>.csv theo schema:
#     ts_utc, ts_local, username, role, content
#     Trả về list[{"role","content","ts"}] đã sắp theo thời gian tăng dần
#     và cắt còn 'limit' cuối cùng.
#     """
#     if not username:
#         return []

#     p = Path(CHAT_LOGS_DIR) / f"{username}.csv"
#     if not p.exists():
#         return []

#     rows = []
#     with p.open("r", encoding="utf-8", newline="") as f:
#         reader = csv.DictReader(f)
#         for r in reader:
#             role = (r.get("role") or "").strip()
#             content = r.get("content") or ""
#             ts = (r.get("ts_utc") or r.get("ts_local") or "").strip()
#             if content:
#                 rows.append({"role": role, "content": content, "ts": ts})

#     # sắp xếp theo ts (nếu parse được ISO)
#     def _key(x):
#         return x.get("ts") or ""
#     rows.sort(key=_key)
#     return rows[-limit:]