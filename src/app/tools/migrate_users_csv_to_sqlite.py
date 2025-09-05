# tools/migrate_users_csv_to_sqlite.py
import os, csv, sqlite3, re, tempfile, shutil, secrets
from werkzeug.security import generate_password_hash

USERS_CSV = os.getenv("USERS_CSV", "./src/app/Data_app/users.csv")
DB_PATH   = os.getenv("SQLITE_PATH") or os.getenv("USERS_DB") or "./src/app/Data_app/users.db"

# === Tuỳ chọn hành vi (qua biến môi trường) ===
# Không ghi lại CSV (mặc định)
WRITE_BACK_CSV = os.getenv("WRITE_BACK_CSV", "0").strip().lower() in {"1","true","yes"}
# Khi thiếu cả password lẫn password_hash:
# - 0: bỏ qua dòng đó (mặc định)
# - 1: tự sinh mật khẩu (in ra console); CSV vẫn không đổi
AUTO_GEN_WHEN_MISSING = os.getenv("AUTO_GEN_WHEN_MISSING", "0").strip().lower() in {"1","true","yes"}
# Nếu muốn dùng cùng 1 mật khẩu cố định cho các dòng thiếu (khi AUTO_GEN_WHEN_MISSING=1)
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "").strip()
# Có lưu plain password vào cột `password` trong DB không (mặc định: có)
STORE_PLAIN_IN_DB = os.getenv("STORE_PLAIN_IN_DB", "1").strip().lower() in {"1","true","yes"}

ALLOWED_ROLES = {"marketing", "manager_marketing", "sales", "hr", "admin", "manager_sales"}
_SPLIT_RE = re.compile(r"[,\s;|/]+")

def _normalize_role_token(tok: str) -> str:
    t = (tok or "").strip().lower().replace("-", "_")
    if t in {"managermarketing", "manager_marketing", "manager marketing"}: return "manager_marketing"
    if t in {"manager_sales", "managersales", "manager sales"}:             return "manager_sales"
    if t == "sale":                                                         return "sales"
    return t

def _split_roles(val):
    if val is None: return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip().lower() for x in val if str(x).strip()]
    return [t.strip().lower() for t in _SPLIT_RE.split(str(val or "")) if t.strip()]

def _gen_password() -> str:
    return DEFAULT_PASSWORD or secrets.token_urlsafe(12)

def ensure_db():
    """
    Tạo bảng nếu chưa có, và đảm bảo tồn tại cột password (plain).
    """
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA busy_timeout=5000;")
        con.execute("""
            CREATE TABLE IF NOT EXISTS users(
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                roles TEXT DEFAULT '',
                password TEXT DEFAULT ''   -- plain password (không khuyến nghị production)
            );
        """)
        con.commit()
        cols = {row[1].lower() for row in con.execute("PRAGMA table_info(users)")}
        if "password" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
            con.commit()
    finally:
        con.close()

def migrate():
    """
    users.csv -> SQLite (KHÔNG sửa CSV trừ khi WRITE_BACK_CSV=1):
      - Nếu thiếu password_hash:
          * nếu có password -> hash từ password
          * nếu không có password:
              - mặc định: BỎ QUA dòng đó
              - nếu AUTO_GEN_WHEN_MISSING=1: tự sinh password (in ra console), CSV vẫn không đổi
      - Ghi DB: username, password_hash, roles, password (tuỳ STORE_PLAIN_IN_DB)
    """
    if not os.path.exists(USERS_CSV):
        print("No users.csv found.")
        return
    ensure_db()

    with open(USERS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    con = sqlite3.connect(DB_PATH, timeout=30)
    generated = []  # [(username, password)]
    upserted = 0
    skipped  = 0
    try:
        for r in rows:
            u  = (r.get('username') or '').strip()
            if not u:
                continue

            ph = (r.get('password_hash') or '').strip()
            pw = (r.get('password') or '').strip()
            role_raw = (r.get('role') or '').strip()

            if not ph:
                if not pw:
                    if AUTO_GEN_WHEN_MISSING:
                        pw = _gen_password()
                        ph = generate_password_hash(pw)
                        generated.append((u, pw))
                    else:
                        print(f"Skip {u}: missing both password and password_hash")
                        skipped += 1
                        continue
                else:
                    ph = generate_password_hash(pw)

            # Chuẩn hoá roles
            toks = [_normalize_role_token(x) for x in _split_roles(role_raw)]
            toks = [t for t in toks if t in ALLOWED_ROLES]
            roles_str = ",".join(dict.fromkeys(toks))  # unique + giữ thứ tự

            # Ghi DB
            con.execute(
                "INSERT INTO users(username,password_hash,roles,password) VALUES(?,?,?,?) "
                "ON CONFLICT(username) DO UPDATE SET "
                "  password_hash=excluded.password_hash, "
                "  roles=excluded.roles, "
                "  password=excluded.password",
                (u, ph, roles_str, (pw if STORE_PLAIN_IN_DB else ""))
            )
            upserted += 1

        con.commit()
    finally:
        con.close()

    # KHÔNG ghi lại CSV (trừ khi bật WRITE_BACK_CSV=1)
    if WRITE_BACK_CSV:
        # Đảm bảo có 2 cột khi ghi lại (nếu bạn chọn bật chế độ này)
        if 'password_hash' not in fieldnames:
            fieldnames.append('password_hash')
        if 'password' not in fieldnames:
            fieldnames.append('password')
        # Cập nhật rows nếu có tự sinh password (chỉ khi muốn ghi CSV)
        rows_map = { (r.get('username') or '').strip(): r for r in rows }
        for u, pw in generated:
            r = rows_map.get(u)
            if r:
                r['password'] = pw
                r['password_hash'] = r.get('password_hash') or '(generated)'
        tmp = tempfile.NamedTemporaryFile("w", delete=False, newline='', encoding='utf-8')
        try:
            w = csv.DictWriter(tmp, fieldnames=fieldnames)
            w.writeheader(); w.writerows(rows)
            tmp.close(); shutil.move(tmp.name, USERS_CSV)
        finally:
            try: os.unlink(tmp.name)
            except Exception: pass

    # Report
    print(f"Migration completed OK. upserted={upserted}, skipped={skipped}")
    if generated:
        print("Generated passwords (CSV không đổi):")
        for u, pw in generated:
            print(f"  - {u}: {pw}")

# if __name__ == "__main__":
#     migrate()
