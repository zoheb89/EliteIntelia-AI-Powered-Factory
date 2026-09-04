"""Authentication and role-based access control.

Design goals
------------
* No plaintext passwords: PBKDF2-HMAC-SHA256 with a per-user salt.
* Stateless sessions: signed, expiring tokens (HMAC-SHA256), so the API can
  scale horizontally without shared session storage.
* Fail closed in production: if ``AUTH_SECRET`` is unset the service refuses to
  issue tokens rather than signing with a guessable default.
* Opt-in rollout: ``AUTH_REQUIRED=false`` keeps existing deployments working
  while auth is being introduced.

Roles map to the personas the product already models. ``admin`` may manage
users; ``editor`` may execute stages and approve; ``viewer`` is read-only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path(os.getenv("CINVENT_DB_PATH", "data/cinvent.db"))
TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL", "43200"))  # 12 hours
PBKDF2_ROUNDS = 240_000

ROLES = ("admin", "editor", "viewer")
# Actions each role may perform. Checked by require_role().
ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}


class AuthError(Exception):
    """Raised for any authentication or authorization failure."""


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "false").strip().lower() in ("1", "true", "yes")


def _secret() -> bytes:
    value = os.getenv("AUTH_SECRET", "").strip()
    if not value:
        if auth_required():
            raise AuthError("AUTH_SECRET is not configured; refusing to sign tokens.")
        # Ephemeral secret for local development only. Tokens die with the process.
        value = _dev_secret()
    return value.encode()


_DEV_SECRET: Optional[str] = None


def _dev_secret() -> str:
    global _DEV_SECRET
    if _DEV_SECRET is None:
        _DEV_SECRET = secrets.token_urlsafe(32)
    return _DEV_SECRET


# ---------------------------------------------------------------- passwords
def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    if not password or len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = stored.split("$")
        if scheme != "pbkdf2":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(rounds))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


# ------------------------------------------------------------------- tokens
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(email: str, role: str, name: str = "") -> str:
    payload = {"sub": email, "role": role, "name": name,
               "iat": int(time.time()), "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> Dict[str, Any]:
    try:
        body, sig = token.split(".")
    except ValueError:
        raise AuthError("Malformed token.")
    expected = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise AuthError("Invalid token signature.")
    payload = json.loads(_b64d(body))
    if payload.get("exp", 0) < time.time():
        raise AuthError("Token has expired.")
    return payload


# -------------------------------------------------------------------- store
class UserStore:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS users(
                email TEXT PRIMARY KEY, name TEXT, role TEXT NOT NULL DEFAULT 'viewer',
                password_hash TEXT NOT NULL, created_at TEXT, last_login TEXT)""")

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT count(*) FROM users").fetchone()[0]

    def get(self, email: str) -> Optional[sqlite3.Row]:
        with self._conn() as c:
            return c.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()

    def create(self, email: str, password: str, name: str = "", role: str = "viewer") -> Dict[str, Any]:
        email = (email or "").lower().strip()
        if "@" not in email:
            raise AuthError("A valid email address is required.")
        if role not in ROLES:
            raise AuthError(f"Role must be one of: {', '.join(ROLES)}")
        if self.get(email):
            raise AuthError("A user with that email already exists.")
        with self._conn() as c:
            c.execute(
                "INSERT INTO users(email, name, role, password_hash, created_at) VALUES(?,?,?,?,datetime('now'))",
                (email, name or email.split("@")[0], role, hash_password(password)),
            )
        return {"email": email, "name": name, "role": role}

    def authenticate(self, email: str, password: str) -> Dict[str, Any]:
        row = self.get(email)
        # Constant-ish work whether or not the user exists, to avoid leaking
        # which emails are registered via response timing.
        stored = row["password_hash"] if row else hash_password("invalid-placeholder-password")
        if not verify_password(password, stored) or not row:
            raise AuthError("Incorrect email or password.")
        with self._conn() as c:
            c.execute("UPDATE users SET last_login = datetime('now') WHERE email = ?", (row["email"],))
        return {"email": row["email"], "name": row["name"], "role": row["role"]}

    def list_users(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT email, name, role, created_at, last_login FROM users ORDER BY created_at")]

    def set_role(self, email: str, role: str):
        if role not in ROLES:
            raise AuthError(f"Role must be one of: {', '.join(ROLES)}")
        with self._conn() as c:
            c.execute("UPDATE users SET role = ? WHERE email = ?", (role, email.lower().strip()))

    def delete(self, email: str):
        with self._conn() as c:
            c.execute("DELETE FROM users WHERE email = ?", (email.lower().strip(),))

    def bootstrap_admin(self) -> Optional[str]:
        """Seed the first admin from env vars so a fresh deploy is usable."""
        email = os.getenv("ADMIN_EMAIL", "").strip()
        password = os.getenv("ADMIN_PASSWORD", "").strip()
        if not email or not password or self.count() > 0:
            return None
        try:
            self.create(email, password, name="Platform Admin", role="admin")
            return email
        except AuthError:
            return None


def require_role(user: Dict[str, Any], minimum: str) -> None:
    if ROLE_RANK.get(user.get("role", "viewer"), 0) < ROLE_RANK[minimum]:
        raise AuthError(f"This action requires the '{minimum}' role or higher.")
