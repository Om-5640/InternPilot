from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import APIError

if TYPE_CHECKING:
    from app.models.user import User

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _make_token(data: dict[str, Any], ttl: int, token_type: str) -> str:
    payload = dict(data)
    payload["exp"] = datetime.now(UTC) + timedelta(seconds=ttl)
    payload["type"] = token_type
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)  # type: ignore[no-any-return]


def create_access_token(data: dict[str, Any]) -> str:
    return _make_token(data, settings.ACCESS_TTL, "access")


def create_refresh_token(data: dict[str, Any]) -> str:
    return _make_token(data, settings.REFRESH_TTL, "refresh")


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG]
        )
    except JWTError as exc:
        raise APIError(401, "INVALID_TOKEN", "Token is invalid or expired") from exc

    if payload.get("type") != expected_type:
        raise APIError(401, "INVALID_TOKEN", f"Expected {expected_type} token")
    return payload


# ---------------------------------------------------------------------------
# Google ID-token verification (wraps synchronous google-auth call)
# ---------------------------------------------------------------------------

async def verify_google_id_token(id_token: str) -> dict[str, Any]:
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token as google_id_token

    loop = asyncio.get_event_loop()

    def _do_verify() -> dict[str, Any]:
        result: dict[str, Any] = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            id_token,
            grequests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
        return result

    try:
        idinfo: dict[str, Any] = await loop.run_in_executor(None, _do_verify)
    except Exception as exc:
        raise APIError(401, "INVALID_TOKEN", f"Google token verification failed: {exc}") from exc
    return idinfo


# ---------------------------------------------------------------------------
# get_current_user FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    from app.models.user import User  # local import avoids circular dependency

    payload = decode_token(token, expected_type="access")
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise APIError(401, "INVALID_TOKEN", "Token missing subject")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise APIError(401, "UNAUTHORIZED", "User not found")
    return user
