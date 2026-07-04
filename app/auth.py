from fastapi import HTTPException, Request
from passlib.context import CryptContext
from time import time

from .config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_admin(username: str, password: str) -> bool:
    return username == settings.admin_username and password == settings.admin_password


def require_login(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    now = int(time())
    last_activity = int(request.session.get("last_activity") or 0)
    if last_activity and now - last_activity > settings.session_idle_timeout_seconds:
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login?expired=1"})
    request.session["last_activity"] = now
