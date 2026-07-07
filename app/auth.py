"""Auth helpers: bcrypt + multi-role (admin vs user)."""
from fastapi import HTTPException, Request
import bcrypt
import hmac

from .config import settings  # noqa: E402
from .database import query_one  # noqa: E402
from time import time  # noqa: E402


# bcrypt has a hard 72-byte input limit. Truncate deterministically so we never
# hit "password cannot be longer than 72 bytes".
_BCRYPT_MAX = 72


def _truncate(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) <= _BCRYPT_MAX:
        return raw
    return raw[:_BCRYPT_MAX]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def verify_credentials(username: str, password: str) -> dict | None:
    """Verify login. Returns a {id, username, role} dict on success."""
    user = query_one(
        "SELECT id, username, password_hash, role FROM users WHERE username = ?",
        (username,),
    )
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


def verify_admin(username: str, password: str) -> bool:
    """Backward-compat shim."""
    user = verify_credentials(username, password)
    return user is not None and user["role"] == "admin"


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_login(request: Request) -> dict:
    """Returns the current user dict. Redirects to /login if not authed."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    now = int(time())
    last_activity = int(request.session.get("last_activity") or 0)
    if last_activity and now - last_activity > settings.session_idle_timeout_seconds:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login?expired=1"})
    request.session["last_activity"] = now
    return user


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang dapat mengakses halaman ini.")
    return user


def require_owner_or_admin(request: Request, site: dict) -> dict:
    """Allow admin, or the user that owns the site (matched by username)."""
    user = require_login(request)
    if user["role"] == "admin":
        return user
    if user["role"] == "user" and user["username"] == site["username"]:
        return user
    raise HTTPException(status_code=403, detail="Anda tidak punya akses ke situs ini.")