from fastapi import HTTPException, Request
from passlib.context import CryptContext

from .config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_admin(username: str, password: str) -> bool:
    return username == settings.admin_username and password == settings.admin_password


def require_login(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
