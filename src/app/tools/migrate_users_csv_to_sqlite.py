import os, csv, sqlite3, re, tempfile, shutil, secrets
from typing import Dict, List, Optional
from werkzeug.security import generate_password_hash
try:
    from app.config.paths import USERS_CSV, USERS_DB
except:
    from src.app.config.paths import USERS_CSV, USERS_DB

WRITE_BACK_CSV = os.getenv("WRITE_BACK_CSV", "0").strip().lower() in {"1","true","yes"}
AUTO_GEN_WHEN_MISSING = os.getenv("AUTO_GEN_WHEN_MISSING", "0").strip().lower() in {"1","true","yes"}
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "").strip()
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
    os.makedirs(os.path.dirname(USERS_DB) or ".", exist_ok=True)
    con = sqlite3.connect(USERS_DB, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA busy_timeout=5000;")
        con.execute("""
            CREATE TABLE IF NOT EXISTS users(
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                roles TEXT DEFAULT '',
                password TEXT DEFAULT ''
            );
        """)
        con.commit()
        cols = {row[1].lower() for row in con.execute("PRAGMA table_info(users)")}
        if "password" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
            con.commit()
    finally:
        con.close()

def _pick_field(fieldnames: List[str], *cands: str) -> Optional[str]:
    """Chọn tên cột đầu tiên có trong fieldnames (case-insensitive)."""
    if not fieldnames: return None
    low = {f.lower(): f for f in fieldnames}
    for c in cands:
        k = c.lower()
        if k in low: return low[k]
    return None

def _sniff_csv(path: str):
    """Trả về (dialect, has_header)."""
    with open(path, "rb") as fb:
        raw = fb.read(65536)
    text_sample = raw.decode("utf-8-sig", errors="ignore")
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text_sample, delimiters=[",",";","|","\t"])
    except Exception:
        class _D(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            doublequote = True
            skipinitialspace = True
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        dialect = _D
    try:
        has_header = sniffer.has_header(text_sample)
    except Exception:
        has_header = True
    return dialect, has_header

def migrate():
    if not os.path.exists(USERS_CSV):
        print(f"[migrate] No users.csv found at: {USERS_CSV}")
        return

    print(f"[migrate] USERS_CSV = {USERS_CSV}")
    print(f"[migrate] USERS_DB   = {USERS_DB}")
    print(f"[migrate] Options   = AUTO_GEN_WHEN_MISSING={AUTO_GEN_WHEN_MISSING}, "
          f"STORE_PLAIN_IN_DB={STORE_PLAIN_IN_DB}, WRITE_BACK_CSV={WRITE_BACK_CSV}")

    ensure_db()

    dialect, _ = _sniff_csv(USERS_CSV)
    with open(USERS_CSV, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, dialect=dialect)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    print(f"[migrate] fieldnames = {fieldnames}")
    print(f"[migrate] total rows = {len(rows)}")

    uname_key = _pick_field(fieldnames, "username", "email", "user", "account", "login", "id")
    roles_key = _pick_field(fieldnames, "roles", "role", "groups", "permissions")
    pass_key  = _pick_field(fieldnames, "password", "pass", "pwd", "plain_password")
    hash_key  = _pick_field(fieldnames, "password_hash", "pass_hash", "hash", "pwd_hash")

    print(f"[migrate] column mapping -> username:{uname_key} roles:{roles_key} "
          f"password:{pass_key} password_hash:{hash_key}")

    if not uname_key:
        print("[migrate] ERROR: CSV không có cột username/email/user/... -> không thể tiếp tục.")
        return

    con = sqlite3.connect(USERS_DB, timeout=30)
    generated = []
    upserted = 0
    skipped  = 0
    empties  = 0
    try:
        for i, r in enumerate(rows, 1):
            u = (r.get(uname_key) or "").strip()
            if not u:
                empties += 1
                continue

            ph = (r.get(hash_key) or "").strip() if hash_key else ""
            pw = (r.get(pass_key) or "").strip() if pass_key else ""
            role_raw = (r.get(roles_key) or "").strip() if roles_key else ""

            if not ph:
                if not pw:
                    if AUTO_GEN_WHEN_MISSING:
                        pw = _gen_password()
                        ph = generate_password_hash(pw)
                        generated.append((u, pw))
                    else:
                        print(f"[migrate] Skip {u}: missing both password and password_hash")
                        skipped += 1
                        continue
                else:
                    ph = generate_password_hash(pw)

            toks = [_normalize_role_token(x) for x in _split_roles(role_raw)]
            toks = [t for t in toks if t in ALLOWED_ROLES]
            roles_str = ",".join(dict.fromkeys(toks))

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

    if WRITE_BACK_CSV:
        if 'password_hash' not in fieldnames:
            fieldnames.append('password_hash')
        if 'password' not in fieldnames:
            fieldnames.append('password')
        rows_map: Dict[str, dict] = { (r.get(uname_key) or '').strip(): r for r in rows }
        for u, pw in generated:
            if u in rows_map:
                rows_map[u]['password'] = pw
                if hash_key:
                    rows_map[u][hash_key] = rows_map[u].get(hash_key) or '(generated)'
        tmp = tempfile.NamedTemporaryFile("w", delete=False, newline='', encoding='utf-8')
        try:
            w = csv.DictWriter(tmp, fieldnames=fieldnames, dialect=dialect)
            w.writeheader(); w.writerows(rows)
            tmp.close(); shutil.move(tmp.name, USERS_CSV)
        finally:
            try: os.unlink(tmp.name)
            except Exception: pass

    print(f"[migrate] DONE. upserted={upserted}, skipped={skipped}, empty-username-rows={empties}")
    if generated:
        print("[migrate] Generated passwords (CSV KHÔNG thay đổi trừ khi WRITE_BACK_CSV=1):")
        for u, pw in generated:
            print(f"  - {u}: {pw}")

