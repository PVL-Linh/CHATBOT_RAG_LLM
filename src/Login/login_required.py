import os, json, csv
from werkzeug.security import generate_password_hash
from functools import wraps
from flask import request, session, redirect, url_for, jsonify



USERS_CSV = os.environ.get("USERS_CSV", "./src/users.csv")
SAVES_DIR = os.path.join(os.path.dirname(__file__), "Data", "saves")
os.makedirs(SAVES_DIR, exist_ok=True)

def load_users():
    users = {}
    if not os.path.exists(USERS_CSV):
        return users
    with open(USERS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            u = (row.get('username') or '').strip()
            ph = (row.get('password_hash') or '').strip()
            pw = (row.get('password') or '').strip()
            if not u:
                continue
            if ph:
                users[u] = {'password_hash': ph}
            elif pw:
                users[u] = {'password_hash': generate_password_hash(pw)}
    return users


def login_required(view=None, *, api=False):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user'):
                if api:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for('login', next=request.path))
            return fn(*args, **kwargs)
        return wrapped
    return deco(view) if view else deco