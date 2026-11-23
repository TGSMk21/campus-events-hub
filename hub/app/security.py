"""Authentication, sessions and role-based access control.

* Passwords: Argon2id (argon2-cffi defaults: 64 MiB, t=3, p=4).
* Sessions: 256-bit CSPRNG token in an HttpOnly + Secure + SameSite=Strict cookie.
  Only SHA-256(token) is stored, so a database leak does not leak live sessions.
* Authorization is always checked on the server (Lab 6, A01). Ownership failures
  on someone else's object return 404 so IDs cannot be probed.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response

from . import db
from .config import get_settings

COOKIE_NAME = "sid"
_ph = PasswordHasher()
# Verified against when the email is unknown, so both failure paths cost the same time.
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(response: Response, user_id: int, user_agent: str = "") -> None:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at, user_agent) VALUES (%s, %s, %s, %s)",
        (_digest(token), user_id, datetime.now(timezone.utc) + timedelta(seconds=s.SESSION_TTL_SECONDS),
         user_agent[:200]),
    )
    response.set_cookie(COOKIE_NAME, token, max_age=s.SESSION_TTL_SECONDS, path="/",
                        httponly=True, secure=s.COOKIE_SECURE, samesite="strict")


def revoke_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = %s", (_digest(token),))   # server side first
    s = get_settings()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=s.COOKIE_SECURE, samesite="strict")


def revoke_all_sessions(user_id: int) -> None:
    db.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


USER_COLUMNS = "u.id, u.email, u.full_name, u.role, u.phone, u.whatsapp_opt_in, u.interests"


def user_from_token(token: str | None) -> dict[str, Any] | None:
    if not token or len(token) > 100:
        return None
    return db.fetch_one(
        f"SELECT {USER_COLUMNS} FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = %s AND s.expires_at > now()",
        (_digest(token),),
    )


def optional_user(request: Request) -> dict[str, Any] | None:
    if "user" not in request.state._state:
        request.state.user = user_from_token(request.cookies.get(COOKIE_NAME))
    return request.state.user


def current_user(user: dict | None = Depends(optional_user)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(401, "Missing, invalid or expired session")
    return user


def require_roles(*roles: str) -> Callable[..., dict[str, Any]]:
    def dependency(user: dict = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(403, f"This action requires the {' or '.join(roles)} role")
        return user
    return dependency


def can_manage(user: dict, owner_id: int) -> bool:
    """Object-level check: the owner or an admin."""
    return user["role"] == "admin" or user["id"] == owner_id


def public_user(u: dict) -> dict[str, Any]:
    return {k: u[k] for k in ("id", "email", "full_name", "role", "phone", "whatsapp_opt_in", "interests")}
