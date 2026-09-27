"""Authentication, revocable sessions, and access administration for SolvAI.

Passwords and browser session tokens are stored only as one-way hashes.
Administrator helpers deliberately return safe account metadata.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import DB_PATH, STORAGE_DIR


PBKDF2_ITERATIONS = 600_000
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
SESSION_DAYS = 7
EVENT_RETENTION_DAYS = 90
VALID_ROLES = {"admin", "editor", "viewer"}
APPROVABLE_ROLES = {"editor", "viewer"}
VALID_REQUEST_STATUSES = {"pending", "approved", "rejected"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthError(ValueError):
    def __init__(self, message: str, code: str = "invalid_request"):
        super().__init__(message)
        self.code = code


def _connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _now():
    return datetime.now(timezone.utc)


def _iso(value=None):
    return (value or _now()).isoformat(timespec="seconds")


def _ensure_column(connection, table, column, definition):
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _token_hash(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _network_hash(address):
    value = str(address or "unknown").strip()
    secret = os.getenv("SOLVAI_AUDIT_SALT", os.getenv("SOLVAI_SECRET_KEY", "solvai-local-audit"))
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _safe_agent(value):
    return (" ".join(str(value or "Unknown device").strip().split())[:240] or "Unknown device")


def _unknown_email_label(email):
    return f"unrecognized:{hashlib.sha256(email.encode('utf-8')).hexdigest()[:12]}"


def normalize_email(email):
    value = str(email or "").strip().lower()
    if len(value) > 254 or not EMAIL_RE.fullmatch(value):
        raise AuthError("Enter a valid email address.", "invalid_email")
    return value


def normalize_name(name):
    value = " ".join(str(name or "").strip().split())
    if len(value) < 2 or len(value) > 80:
        raise AuthError("Enter a name between 2 and 80 characters.", "invalid_name")
    return value


def validate_password(password):
    value = str(password or "")
    if len(value) < 12:
        raise AuthError("Use at least 12 characters for your password.", "weak_password")
    if len(value) > 256:
        raise AuthError("Password is too long.", "weak_password")
    if value.lower() == value or value.upper() == value or not any(ch.isdigit() for ch in value):
        raise AuthError("Use uppercase, lowercase, and at least one number.", "weak_password")
    return value


def hash_password(password):
    value = validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "$".join(("pbkdf2_sha256", str(PBKDF2_ITERATIONS),
                     base64.urlsafe_b64encode(salt).decode("ascii"),
                     base64.urlsafe_b64encode(digest).decode("ascii")))


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_text, digest_text = str(encoded).split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        candidate = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(candidate, expected)
    except (TypeError, ValueError, UnicodeError):
        return False


def init_auth_db():
    Path(STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                workspace_id TEXT NOT NULL DEFAULT 'default',
                is_active INTEGER NOT NULL DEFAULT 1,
                must_reset_password INTEGER NOT NULL DEFAULT 0,
                session_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                password_changed_at TEXT,
                last_login_at TEXT,
                login_count INTEGER NOT NULL DEFAULT 0,
                failed_login_count INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            );
            CREATE TABLE IF NOT EXISTS login_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT NOT NULL,
                event TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                network_hash TEXT,
                user_agent TEXT,
                detail TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                session_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                network_hash TEXT,
                user_agent TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS admin_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER,
                target_user_id INTEGER,
                action TEXT NOT NULL,
                detail TEXT,
                occurred_at TEXT NOT NULL,
                FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS access_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                requested_role TEXT NOT NULL DEFAULT 'viewer',
                request_note TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                workspace_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                approved_user_id INTEGER,
                decision_note TEXT,
                network_hash TEXT,
                user_agent TEXT,
                FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(approved_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_login_events_time ON login_events(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id,revoked_at,expires_at);
            CREATE INDEX IF NOT EXISTS idx_admin_audit_time ON admin_audit(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_access_requests_status_time
                ON access_requests(status,created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_access_requests_pending_email
                ON access_requests(email) WHERE status='pending';
        """)
        for table, column, definition in (
            ("users", "workspace_id", "TEXT NOT NULL DEFAULT 'default'"),
            ("users", "must_reset_password", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "session_version", "INTEGER NOT NULL DEFAULT 1"),
            ("users", "password_changed_at", "TEXT"),
            ("login_events", "network_hash", "TEXT"),
            ("login_events", "user_agent", "TEXT"),
            ("login_events", "detail", "TEXT"),
            ("access_requests", "workspace_id", "TEXT NOT NULL DEFAULT 'default'"),
            ("access_requests", "reviewed_at", "TEXT"),
            ("access_requests", "reviewed_by", "INTEGER"),
            ("access_requests", "approved_user_id", "INTEGER"),
            ("access_requests", "decision_note", "TEXT"),
            ("access_requests", "network_hash", "TEXT"),
            ("access_requests", "user_agent", "TEXT"),
        ):
            _ensure_column(connection, table, column, definition)
        connection.execute("UPDATE users SET role='viewer' WHERE role='user'")
    prune_security_history()


def _safe_user(row):
    if not row:
        return None
    keys = set(row.keys())
    return {
        "id": int(row["id"]), "email": row["email"], "display_name": row["display_name"],
        "role": "viewer" if row["role"] == "user" else row["role"],
        "workspace_id": row["workspace_id"] if "workspace_id" in keys else "default",
        "is_active": bool(row["is_active"]),
        "must_reset_password": bool(row["must_reset_password"]) if "must_reset_password" in keys else False,
        "created_at": row["created_at"],
        "password_changed_at": row["password_changed_at"] if "password_changed_at" in keys else None,
        "last_login_at": row["last_login_at"], "login_count": int(row["login_count"] or 0),
        "failed_login_count": int(row["failed_login_count"] or 0), "locked_until": row["locked_until"],
        "active_session_count": int(row["active_session_count"] or 0) if "active_session_count" in keys else 0,
        "last_failed_at": row["last_failed_at"] if "last_failed_at" in keys else None,
    }


def _safe_access_request(row):
    """Return review metadata without ever exposing the stored password hash."""
    if not row:
        return None
    keys = set(row.keys())
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "display_name": row["display_name"],
        "requested_role": row["requested_role"] if "requested_role" in keys else "viewer",
        "request_note": row["request_note"] if "request_note" in keys else "",
        "status": row["status"],
        "workspace_id": row["workspace_id"] if "workspace_id" in keys else "default",
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"] if "reviewed_at" in keys else None,
        "reviewed_by": row["reviewed_by"] if "reviewed_by" in keys else None,
        "reviewer_email": row["reviewer_email"] if "reviewer_email" in keys else None,
        "approved_user_id": row["approved_user_id"] if "approved_user_id" in keys else None,
        "decision_note": row["decision_note"] if "decision_note" in keys else "",
        "network_hash": row["network_hash"] if "network_hash" in keys else None,
        "user_agent": row["user_agent"] if "user_agent" in keys else None,
    }


def _record_event(connection, user_id, email, event, *, address=None, user_agent=None, detail=None):
    connection.execute(
        "INSERT INTO login_events(user_id,email,event,occurred_at,network_hash,user_agent,detail) VALUES(?,?,?,?,?,?,?)",
        (user_id, email, event, _iso(), _network_hash(address), _safe_agent(user_agent), str(detail or "")[:300]),
    )


def user_count():
    with _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def readiness_check():
    """Check database availability without exposing account or path details."""
    try:
        init_auth_db()
        with _connect() as connection:
            connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return True
    except Exception:
        return False


def create_user(email, password, display_name, *, role=None, actor_id=None):
    clean_email = normalize_email(email)
    clean_name = normalize_name(display_name)
    assigned_role = str(role or "viewer").strip().lower()
    if assigned_role == "user":
        assigned_role = "viewer"
    if assigned_role not in VALID_ROLES:
        raise AuthError("Role must be admin, editor, or viewer.", "invalid_role")
    password_hash = hash_password(password)
    created_at = _iso()
    workspace_id = str(os.getenv("SOLVAI_WORKSPACE_ID", "default")).strip()[:64] or "default"
    with _connect() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users(email,password_hash,display_name,role,workspace_id,created_at,password_changed_at) VALUES(?,?,?,?,?,?,?)",
                (clean_email, password_hash, clean_name, assigned_role, workspace_id, created_at, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise AuthError("An account already exists for this email.", "email_exists") from exc
        user_id = int(cursor.lastrowid)
        _record_event(connection, user_id, clean_email, "account_created")
        if actor_id is not None:
            connection.execute(
                "INSERT INTO admin_audit(actor_user_id,target_user_id,action,detail,occurred_at) VALUES(?,?,?,?,?)",
                (int(actor_id), user_id, "account_created", f"role={assigned_role}", _iso()),
            )
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _safe_user(row)


def create_access_request(email, password, display_name, *, request_note=None, address=None, user_agent=None):
    """Store a pending self-registration request for administrator review.

    The supplied password is validated and one-way hashed before the database
    write. Neither list nor admin APIs return the hash.
    """
    clean_email = normalize_email(email)
    clean_name = normalize_name(display_name)
    note = " ".join(str(request_note or "").strip().split())[:500]
    password_hash = hash_password(password)
    workspace_id = str(os.getenv("SOLVAI_WORKSPACE_ID", "default")).strip()[:64] or "default"
    created_at = _iso()
    with _connect() as connection:
        if connection.execute("SELECT 1 FROM users WHERE email=?", (clean_email,)).fetchone():
            raise AuthError("An account already exists for this email.", "email_exists")
        if connection.execute(
            "SELECT 1 FROM access_requests WHERE email=? AND status='pending'", (clean_email,)
        ).fetchone():
            raise AuthError("An access request for this email is already awaiting review.", "request_pending")
        try:
            cursor = connection.execute("""
                INSERT INTO access_requests(
                    email,password_hash,display_name,requested_role,request_note,status,
                    workspace_id,created_at,network_hash,user_agent
                ) VALUES(?,?,?,?,?,'pending',?,?,?,?)
            """, (
                clean_email, password_hash, clean_name, "viewer", note,
                workspace_id, created_at, _network_hash(address), _safe_agent(user_agent),
            ))
        except sqlite3.IntegrityError as exc:
            raise AuthError("An access request for this email is already awaiting review.", "request_pending") from exc
        _record_event(
            connection, None, clean_email, "access_requested",
            address=address, user_agent=user_agent, detail=f"request_id={int(cursor.lastrowid)}",
        )
        row = connection.execute("SELECT * FROM access_requests WHERE id=?", (cursor.lastrowid,)).fetchone()
    return _safe_access_request(row)


def list_access_requests(*, status=None, workspace_id=None, limit=200):
    safe_limit = max(1, min(500, int(limit)))
    clauses = []
    params = []
    if status is not None:
        clean_status = str(status).strip().lower()
        if clean_status not in VALID_REQUEST_STATUSES:
            raise AuthError("Request status must be pending, approved, or rejected.", "invalid_status")
        clauses.append("r.status=?")
        params.append(clean_status)
    if workspace_id is not None:
        clauses.append("r.workspace_id=?")
        params.append(str(workspace_id).strip()[:64] or "default")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(safe_limit)
    with _connect() as connection:
        rows = connection.execute(f"""
            SELECT r.*,reviewer.email reviewer_email
            FROM access_requests r
            LEFT JOIN users reviewer ON reviewer.id=r.reviewed_by
            {where}
            ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,
                     datetime(r.created_at) DESC,r.id DESC
            LIMIT ?
        """, tuple(params)).fetchall()
    return [_safe_access_request(row) for row in rows]


def pending_access_request_count(*, workspace_id=None):
    clauses = ["status='pending'"]
    params = []
    if workspace_id is not None:
        clauses.append("workspace_id=?")
        params.append(str(workspace_id).strip()[:64] or "default")
    with _connect() as connection:
        return int(connection.execute(
            f"SELECT COUNT(*) FROM access_requests WHERE {' AND '.join(clauses)}", tuple(params)
        ).fetchone()[0])


def review_access_request(request_id, action, *, role="viewer", actor_id, decision_note=None):
    clean_action = str(action or "").strip().lower()
    if clean_action not in {"approve", "reject"}:
        raise AuthError("Request action must be approve or reject.", "invalid_action")
    clean_role = str(role or "viewer").strip().lower()
    if clean_action == "approve" and clean_role not in APPROVABLE_ROLES:
        raise AuthError("Approved access must use the Viewer or Editor role.", "invalid_role")
    note = " ".join(str(decision_note or "").strip().split())[:500]
    reviewed_at = _iso()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        request_row = connection.execute("SELECT * FROM access_requests WHERE id=?", (int(request_id),)).fetchone()
        if not request_row:
            raise AuthError("Access request not found.", "not_found")
        if request_row["status"] != "pending":
            raise AuthError("This access request has already been reviewed.", "already_reviewed")
        actor = _target(connection, actor_id)
        if actor["role"] != "admin" or not bool(actor["is_active"]):
            raise AuthError("An active administrator is required.", "forbidden")
        if request_row["workspace_id"] != actor["workspace_id"]:
            raise AuthError("This request belongs to another workspace.", "forbidden")

        approved_user = None
        if clean_action == "approve":
            if connection.execute("SELECT 1 FROM users WHERE email=?", (request_row["email"],)).fetchone():
                raise AuthError("An account already exists for this email.", "email_exists")
            cursor = connection.execute("""
                INSERT INTO users(
                    email,password_hash,display_name,role,workspace_id,created_at,password_changed_at
                ) VALUES(?,?,?,?,?,?,?)
            """, (
                request_row["email"], request_row["password_hash"], request_row["display_name"],
                clean_role, request_row["workspace_id"], reviewed_at, reviewed_at,
            ))
            user_id = int(cursor.lastrowid)
            connection.execute("""
                UPDATE access_requests
                SET status='approved',password_hash='',reviewed_at=?,reviewed_by=?,
                    approved_user_id=?,decision_note=?
                WHERE id=?
            """, (reviewed_at, int(actor_id), user_id, note, int(request_id)))
            _record_event(
                connection, user_id, request_row["email"], "account_created",
                detail=f"approved_request={int(request_id)}",
            )
            _audit(connection, actor_id, user_id, "access_request_approved",
                   f"request_id={int(request_id)};role={clean_role}")
            approved_user = _safe_user(connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        else:
            connection.execute("""
                UPDATE access_requests
                SET status='rejected',password_hash='',reviewed_at=?,reviewed_by=?,decision_note=?
                WHERE id=?
            """, (reviewed_at, int(actor_id), note, int(request_id)))
            _record_event(
                connection, None, request_row["email"], "access_request_rejected",
                detail=f"request_id={int(request_id)}",
            )
            _audit(connection, actor_id, None, "access_request_rejected", f"request_id={int(request_id)}")

        reviewed = connection.execute("""
            SELECT r.*,reviewer.email reviewer_email
            FROM access_requests r LEFT JOIN users reviewer ON reviewer.id=r.reviewed_by
            WHERE r.id=?
        """, (int(request_id),)).fetchone()
    return {"request": _safe_access_request(reviewed), "user": approved_user}


def get_user(user_id):
    try:
        identifier = int(user_id)
    except (TypeError, ValueError):
        return None
    with _connect() as connection:
        return _safe_user(connection.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone())


def authenticate(email, password, *, address=None, user_agent=None):
    clean_email = normalize_email(email)
    now = _now()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE email=?", (clean_email,)).fetchone()
        if not row:
            hashlib.pbkdf2_hmac("sha256", str(password or "").encode(), b"solvai-dummy-salt", PBKDF2_ITERATIONS)
            _record_event(connection, None, _unknown_email_label(clean_email), "login_failed",
                          address=address, user_agent=user_agent, detail="unrecognized_account")
            connection.commit()
            raise AuthError("Email or password is incorrect.", "invalid_credentials")
        if not bool(row["is_active"]):
            _record_event(connection, row["id"], clean_email, "login_blocked",
                          address=address, user_agent=user_agent, detail="inactive")
            connection.commit()
            raise AuthError("This account is inactive. Contact the workspace administrator.", "inactive")
        locked_until = row["locked_until"]
        lock_expired = False
        if locked_until:
            try:
                unlock_at = datetime.fromisoformat(locked_until)
            except ValueError:
                unlock_at = now
            if unlock_at > now:
                _record_event(connection, row["id"], clean_email, "login_blocked",
                              address=address, user_agent=user_agent, detail="locked")
                connection.commit()
                raise AuthError("Too many attempts. Try again in a few minutes.", "locked")
            lock_expired = True
        if not verify_password(password, row["password_hash"]):
            failed = (0 if lock_expired else int(row["failed_login_count"] or 0)) + 1
            next_unlock = _iso(now + timedelta(minutes=LOCK_MINUTES)) if failed >= MAX_FAILED_ATTEMPTS else None
            connection.execute("UPDATE users SET failed_login_count=?,locked_until=? WHERE id=?",
                               (failed, next_unlock, row["id"]))
            _record_event(connection, row["id"], clean_email, "login_failed", address=address, user_agent=user_agent)
            connection.commit()
            raise AuthError("Email or password is incorrect.", "invalid_credentials")
        connection.execute(
            "UPDATE users SET last_login_at=?,login_count=login_count+1,failed_login_count=0,locked_until=NULL WHERE id=?",
            (_iso(now), row["id"]),
        )
        _record_event(connection, row["id"], clean_email, "login_succeeded", address=address, user_agent=user_agent)
        updated = connection.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
    return _safe_user(updated)


def start_session(user_id, *, remember=False, address=None, user_agent=None):
    user = get_user(user_id)
    if not user or not user["is_active"]:
        raise AuthError("This account cannot start a session.", "inactive")
    token = secrets.token_urlsafe(48)
    now = _now()
    lifetime = timedelta(days=SESSION_DAYS if remember else 1)
    with _connect() as connection:
        version = int(connection.execute("SELECT session_version FROM users WHERE id=?", (user_id,)).fetchone()[0])
        connection.execute(
            "INSERT INTO auth_sessions(user_id,token_hash,session_version,created_at,last_seen_at,expires_at,network_hash,user_agent) VALUES(?,?,?,?,?,?,?,?)",
            (user_id, _token_hash(token), version, _iso(now), _iso(now), _iso(now + lifetime),
             _network_hash(address), _safe_agent(user_agent)),
        )
    return token


def validate_session(user_id, token):
    try:
        identifier = int(user_id)
    except (TypeError, ValueError):
        return None, None
    if not token:
        return None, None
    now = _now()
    with _connect() as connection:
        active = connection.execute(
            "SELECT * FROM auth_sessions WHERE user_id=? AND token_hash=?", (identifier, _token_hash(token))
        ).fetchone()
        user_row = connection.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone()
        if not active or not user_row or active["revoked_at"] or not bool(user_row["is_active"]):
            return None, None
        try:
            expired = datetime.fromisoformat(active["expires_at"]) <= now
        except (TypeError, ValueError):
            expired = True
        if expired or int(active["session_version"]) != int(user_row["session_version"]):
            connection.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                               (_iso(now), active["id"]))
            return None, None
        connection.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (_iso(now), active["id"]))
        safe_session = {key: active[key] for key in
                        ("id", "created_at", "last_seen_at", "expires_at", "network_hash", "user_agent")}
        safe_session["last_seen_at"] = _iso(now)
    return _safe_user(user_row), safe_session


def revoke_session(session_id, *, user_id=None):
    with _connect() as connection:
        if user_id is None:
            cursor = connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (_iso(), int(session_id))
            )
        else:
            cursor = connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                (_iso(), int(session_id), int(user_id)),
            )
    return bool(cursor.rowcount)


def revoke_user_sessions(user_id, *, except_session_id=None):
    with _connect() as connection:
        if except_session_id is None:
            cursor = connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (_iso(), int(user_id))
            )
        else:
            cursor = connection.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND id<>? AND revoked_at IS NULL",
                (_iso(), int(user_id), int(except_session_id)),
            )
    return int(cursor.rowcount or 0)


def record_logout(user, session_id=None):
    if not user:
        return
    if session_id is not None:
        revoke_session(session_id, user_id=user["id"])
    with _connect() as connection:
        _record_event(connection, user["id"], user["email"], "logout")


def list_sessions(user_id, *, active_only=True):
    where = "AND revoked_at IS NULL AND expires_at>?" if active_only else ""
    params = (int(user_id), _iso()) if active_only else (int(user_id),)
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT id,created_at,last_seen_at,expires_at,revoked_at,network_hash,user_agent FROM auth_sessions WHERE user_id=? {where} ORDER BY id DESC",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def list_users():
    with _connect() as connection:
        rows = connection.execute("""
            SELECT u.*,
              (SELECT COUNT(*) FROM auth_sessions s WHERE s.user_id=u.id AND s.revoked_at IS NULL AND s.expires_at>?) AS active_session_count,
              (SELECT occurred_at FROM login_events e WHERE e.user_id=u.id AND e.event='login_failed' ORDER BY e.id DESC LIMIT 1) AS last_failed_at
            FROM users u ORDER BY datetime(u.created_at) DESC,u.id DESC
        """, (_iso(),)).fetchall()
    return [_safe_user(row) for row in rows]


def recent_login_events(limit=50):
    safe_limit = max(1, min(200, int(limit)))
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id,user_id,email,event,occurred_at,network_hash,user_agent,detail FROM login_events ORDER BY id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_admin_audit(limit=50):
    with _connect() as connection:
        rows = connection.execute("""
            SELECT a.*,actor.email actor_email,target.email target_email
            FROM admin_audit a LEFT JOIN users actor ON actor.id=a.actor_user_id
            LEFT JOIN users target ON target.id=a.target_user_id
            ORDER BY a.id DESC LIMIT ?
        """, (max(1, min(200, int(limit))),)).fetchall()
    return [dict(row) for row in rows]


def _audit(connection, actor_id, target_id, action, detail=""):
    connection.execute(
        "INSERT INTO admin_audit(actor_user_id,target_user_id,action,detail,occurred_at) VALUES(?,?,?,?,?)",
        (
            int(actor_id), int(target_id) if target_id is not None else None,
            action, str(detail or "")[:300], _iso(),
        ),
    )


def _target(connection, user_id):
    row = connection.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    if not row:
        raise AuthError("Account not found.", "not_found")
    return row


def _protect_last_admin(connection, target, removing_admin):
    if removing_admin and target["role"] == "admin":
        count = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0])
        if count <= 1:
            raise AuthError("The workspace must keep at least one active administrator.", "last_admin")


def set_active(user_id, active, *, actor_id):
    with _connect() as connection:
        target = _target(connection, user_id)
        if int(target["id"]) == int(actor_id) and not active:
            raise AuthError("You cannot deactivate your current administrator account.", "self_protected")
        _protect_last_admin(connection, target, not active)
        connection.execute("UPDATE users SET is_active=? WHERE id=?", (int(bool(active)), target["id"]))
        if not active:
            connection.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                               (_iso(), target["id"]))
        _audit(connection, actor_id, target["id"], "account_activated" if active else "account_deactivated")
        row = connection.execute("SELECT * FROM users WHERE id=?", (target["id"],)).fetchone()
    return _safe_user(row)


def set_role(identifier, role, *, actor_id=None):
    clean_role = str(role or "").strip().lower()
    if clean_role == "user":
        clean_role = "viewer"
    if clean_role not in VALID_ROLES:
        raise AuthError("Role must be admin, editor, or viewer.", "invalid_role")
    with _connect() as connection:
        if isinstance(identifier, str) and "@" in identifier:
            target = connection.execute("SELECT * FROM users WHERE email=?", (normalize_email(identifier),)).fetchone()
            if not target:
                raise AuthError("Account not found.", "not_found")
        else:
            target = _target(connection, identifier)
        _protect_last_admin(connection, target, target["role"] == "admin" and clean_role != "admin")
        connection.execute("UPDATE users SET role=? WHERE id=?", (clean_role, target["id"]))
        if actor_id is not None:
            _audit(connection, actor_id, target["id"], "role_changed", f"role={clean_role}")
        row = connection.execute("SELECT * FROM users WHERE id=?", (target["id"],)).fetchone()
    return _safe_user(row)


def unlock_user(user_id, *, actor_id):
    with _connect() as connection:
        target = _target(connection, user_id)
        connection.execute("UPDATE users SET failed_login_count=0,locked_until=NULL WHERE id=?", (target["id"],))
        _audit(connection, actor_id, target["id"], "account_unlocked")
        row = connection.execute("SELECT * FROM users WHERE id=?", (target["id"],)).fetchone()
    return _safe_user(row)


def require_password_reset(user_id, *, actor_id):
    with _connect() as connection:
        target = _target(connection, user_id)
        connection.execute(
            "UPDATE users SET must_reset_password=1,session_version=session_version+1 WHERE id=?", (target["id"],)
        )
        connection.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                           (_iso(), target["id"]))
        _audit(connection, actor_id, target["id"], "password_reset_required")
        row = connection.execute("SELECT * FROM users WHERE id=?", (target["id"],)).fetchone()
    return _safe_user(row)


def admin_revoke_user_sessions(user_id, *, actor_id):
    with _connect() as connection:
        target = _target(connection, user_id)
        cursor = connection.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (_iso(), target["id"])
        )
        _audit(connection, actor_id, target["id"], "sessions_revoked", f"count={int(cursor.rowcount or 0)}")
    return int(cursor.rowcount or 0)


def change_password(user_id, current_password, new_password):
    new_hash = hash_password(new_password)
    with _connect() as connection:
        target = _target(connection, user_id)
        if not verify_password(current_password, target["password_hash"]):
            raise AuthError("Current password is incorrect.", "invalid_credentials")
        connection.execute("""
            UPDATE users SET password_hash=?,password_changed_at=?,must_reset_password=0,
            session_version=session_version+1,failed_login_count=0,locked_until=NULL WHERE id=?
        """, (new_hash, _iso(), target["id"]))
        connection.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                           (_iso(), target["id"]))
        _record_event(connection, target["id"], target["email"], "password_changed")
        row = connection.execute("SELECT * FROM users WHERE id=?", (target["id"],)).fetchone()
    return _safe_user(row)


def set_password(email, password):
    clean_email = normalize_email(email)
    password_hash = hash_password(password)
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE email=?", (clean_email,)).fetchone()
        if not row:
            raise AuthError("Account not found.", "not_found")
        connection.execute("""
            UPDATE users SET password_hash=?,password_changed_at=?,must_reset_password=0,
            session_version=session_version+1,failed_login_count=0,locked_until=NULL WHERE id=?
        """, (password_hash, _iso(), row["id"]))
        connection.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                           (_iso(), row["id"]))
        row = connection.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
    return _safe_user(row)


def delete_user(user_id, *, actor_id):
    with _connect() as connection:
        target = _target(connection, user_id)
        if int(target["id"]) == int(actor_id):
            raise AuthError("You cannot remove the account you are currently using.", "self_protected")
        if bool(target["is_active"]):
            raise AuthError("Deactivate the account before removing it.", "deactivate_first")
        _protect_last_admin(connection, target, True)
        _audit(connection, actor_id, target["id"], "account_removed")
        connection.execute("DELETE FROM users WHERE id=?", (target["id"],))


def prune_security_history(days=EVENT_RETENTION_DAYS):
    cutoff = _iso(_now() - timedelta(days=max(30, int(days))))
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM login_events WHERE occurred_at<?", (cutoff,))
        connection.execute(
            "DELETE FROM auth_sessions WHERE expires_at<? OR (revoked_at IS NOT NULL AND revoked_at<?)",
            (cutoff, cutoff),
        )
        connection.execute(
            "DELETE FROM access_requests WHERE status<>'pending' AND reviewed_at IS NOT NULL AND reviewed_at<?",
            (cutoff,),
        )
    return int(cursor.rowcount or 0)


def bootstrap_admin_from_env():
    email = os.getenv("SOLVAI_ADMIN_EMAIL", "").strip()
    password = os.getenv("SOLVAI_ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    try:
        clean_email = normalize_email(email)
        with _connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE email=?", (clean_email,)).fetchone()
            if row:
                connection.execute("UPDATE users SET role='admin',is_active=1 WHERE id=?", (row["id"],))
                return _safe_user(connection.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone())
        return create_user(clean_email, password, os.getenv("SOLVAI_ADMIN_NAME", "Workspace Admin"), role="admin")
    except AuthError as exc:
        print(f"SolvAI admin bootstrap skipped: {exc}")
        return None


def session_secret():
    configured = os.getenv("SOLVAI_SECRET_KEY", "").strip()
    if configured:
        return configured
    if os.getenv("SOLVAI_ENV", "development").strip().lower() in {"production", "prod"}:
        raise RuntimeError("SOLVAI_SECRET_KEY is required when SOLVAI_ENV=production.")
    Path(STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    secret_path = Path(STORAGE_DIR) / ".session_secret"
    if secret_path.exists() and secret_path.read_text(encoding="utf-8").strip():
        return secret_path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
    except FileExistsError:
        value = secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return value
