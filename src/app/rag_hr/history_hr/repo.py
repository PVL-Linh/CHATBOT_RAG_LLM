# -*- coding: utf-8 -*-
# app/rag_hr/repo.py
from __future__ import annotations
from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, Optional, List

from .storage import get_conn

def create_session(user: str, title: str = "Cuộc trò chuyện HR") -> str:
    sid = str(uuid4())
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO hr_sessions (id, user, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (sid, user or "anonymous", title, now, now),
    )
    conn.commit()
    conn.close()
    return sid

def add_message(session_id: str, role: str, content: str) -> None:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO hr_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now),
    )
    cur.execute("UPDATE hr_sessions SET updated_at=? WHERE id=?", (now, session_id))
    conn.commit()
    conn.close()

def list_sessions(user: str, limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.title, s.created_at, s.updated_at,
               (SELECT content FROM hr_messages
                WHERE session_id=s.id AND role='user'
                ORDER BY timestamp ASC LIMIT 1) AS preview
        FROM hr_sessions s
        WHERE s.user=?
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (user, limit))
    rows = cur.fetchall()
    conn.close()
    return [{
        "id": r[0],
        "title": r[1],
        "first_ts": r[2],
        "last_ts": r[3],
        "preview": (r[4] or "")[:100],
    } for r in rows]

def get_messages(session_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content, timestamp AS ts FROM hr_messages WHERE session_id=? ORDER BY timestamp ASC",
        (session_id,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def rename_session(session_id: str, title: str) -> None:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE hr_sessions SET title=?, updated_at=? WHERE id=?",
                (title, now, session_id))
    conn.commit()
    conn.close()

def delete_session(session_id: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM hr_messages WHERE session_id=?", (session_id,))
    cur.execute("DELETE FROM hr_sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()

def latest_session(user: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM hr_sessions WHERE user=? ORDER BY updated_at DESC LIMIT 1", (user,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    sid = row[0]
    items = get_messages(sid)
    conn.close()
    return {"session_id": sid, "items": items}

def get_session_owner(session_id: str) -> Optional[str]:
    if not session_id:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user FROM hr_sessions WHERE id=?", (session_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
