import os, json, shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from tempfile import NamedTemporaryFile
from flask import session, current_app as app

MAX_HISTORY    = int(os.environ.get("MAX_HISTORY", "50"))
CHAT_LOGS_DIR  = os.environ.get("CHAT_LOGS_DIR", "./src/app/Data_app/chat_logs")
CHAT_LOGS_FILE = os.environ.get("CHAT_LOGS_FILE", "chat_logs.json")
LOCAL_TZ_NAME  = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

# ---------- helpers ----------
def _store_path() -> Path:
    p = Path(CHAT_LOGS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p / CHAT_LOGS_FILE

def _json_load_obj(fp: Path) -> dict:
    if not fp.exists():
        return {"name": 1, "messages": []}
    try:
        with fp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"name": 1, "messages": []}
        data.setdefault("name", 1)
        data.setdefault("messages", [])
        if not isinstance(data["messages"], list):
            data["messages"] = []
        return data
    except Exception:
        return {"name": 1, "messages": []}

def _json_atomic_write_obj(fp: Path, data: dict):
    tmp = NamedTemporaryFile("w", delete=False, encoding="utf-8", newline="")
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
    finally:
        tmp.close()
    shutil.move(tmp.name, fp)

def _now_local_pair(ts_utc_iso: str):
    # chuẩn hoá UTC + tạo local
    try:
        ts_utc = datetime.fromisoformat(ts_utc_iso.replace("Z", "+00:00"))
    except Exception:
        ts_utc = datetime.now(timezone.utc)
        ts_utc_iso = ts_utc.isoformat()
    try:
        local_tz = ZoneInfo(LOCAL_TZ_NAME)
    except Exception:
        local_tz = timezone.utc
    ts_local_iso = ts_utc.astimezone(local_tz).isoformat()
    return ts_utc_iso, ts_local_iso

# ---------- storage (turn-based) ----------
def _append_user_turn(data: dict, username: str, session_id: str, ts_utc_iso: str, content: str):
    ts_utc_iso, ts_local_iso = _now_local_pair(ts_utc_iso)
    data["messages"].append({
        "username": username,
        "session_id": session_id or "",
        "ts_utc_user": ts_utc_iso,
        "ts_local_user": ts_local_iso,
        "content_user": content or "",
        # assistant fields có thể bổ sung sau
    })

def _attach_assistant_to_last_turn(data: dict, username: str, session_id: str, ts_utc_iso: str, content: str):
    ts_utc_iso, ts_local_iso = _now_local_pair(ts_utc_iso)
    # tìm turn gần nhất cùng user+sid chưa có assistant
    for item in reversed(data["messages"]):
        if item.get("username") == username and (item.get("session_id") or "") == (session_id or ""):
            if not item.get("content_assistant"):
                item["ts_utc_assistant"] = ts_utc_iso
                item["ts_local_assistant"] = ts_local_iso
                item["content_assistant"] = content or ""
                return True
            break
    return False  # không gắn được

def _log_message_to_json_turn(username: str, role: str, content: str, ts_utc_iso: str, session_id: str = ""):
    if not username:
        return
    fp = _store_path()
    data = _json_load_obj(fp)

    if role == "user":
        _append_user_turn(data, username, session_id, ts_utc_iso, content)
    elif role == "assistant":
        ok = _attach_assistant_to_last_turn(data, username, session_id, ts_utc_iso, content)
        if not ok:
            # edge case: chưa có user turn, vẫn ghi 1 turn với assistant trước
            ts_utc_iso, ts_local_iso = _now_local_pair(ts_utc_iso)
            data["messages"].append({
                "username": username,
                "session_id": session_id or "",
                "ts_utc_assistant": ts_utc_iso,
                "ts_local_assistant": ts_local_iso,
                "content_assistant": content or ""
            })
    else:
        # vai trò khác -> vẫn ghi riêng 1 turn để không mất dữ liệu
        ts_utc_iso, ts_local_iso = _now_local_pair(ts_utc_iso)
        data["messages"].append({
            "username": username,
            "session_id": session_id or "",
            "ts_utc_user": ts_utc_iso,
            "ts_local_user": ts_local_iso,
            "content_user": f"[{role}] {content or ''}"
        })

    _json_atomic_write_obj(fp, data)

# ---------- Flask session helpers ----------
def get_history():
    msgs = session.get("messages") or []
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
        session["messages"] = msgs
    return msgs

def add_message(role, content, session_id: str = ""):
    # vẫn giữ session memory cho UI
    msgs = get_history()
    ts_utc_iso = datetime.now(timezone.utc).isoformat()
    msgs.append({"role": role, "content": content, "ts": ts_utc_iso, "session_id": session_id or ""})
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
    session["messages"] = msgs

    try:
        user = session.get("user")
        _log_message_to_json_turn(user, role, content, ts_utc_iso, session_id or "")
    except Exception as e:
        try:
            app.logger.exception("Failed to write chat JSON(turn): %s", e)
        except Exception:
            pass

# ---------- Public API cho routes ----------
def read_sessions_and_messages(username: str):
    """
    Đọc file chung -> lọc theo username -> GOM THEO session_id,
    và CHUYỂN về dạng list message như cũ:
      [{"role":"user","content":...,"ts":...}, {"role":"assistant",...}, ...]
    """
    fp = _store_path()
    data = _json_load_obj(fp)
    sessions = {}

    for item in data.get("messages", []):
        if (item.get("username") or "").strip() != (username or "").strip():
            continue
        sid = (item.get("session_id") or "").strip() or "default"

        # nếu có user
        if item.get("content_user"):
            ts = (item.get("ts_utc_user") or item.get("ts_local_user") or "").strip()
            sessions.setdefault(sid, []).append({
                "role": "user",
                "content": item.get("content_user") or "",
                "ts": ts
            })
        # nếu có assistant
        if item.get("content_assistant"):
            ts = (item.get("ts_utc_assistant") or item.get("ts_local_assistant") or "").strip()
            sessions.setdefault(sid, []).append({
                "role": "assistant",
                "content": item.get("content_assistant") or "",
                "ts": ts
            })

    # sort theo ts trong từng session
    for sid in sessions:
        sessions[sid].sort(key=lambda x: x.get("ts") or "")

    return sessions
