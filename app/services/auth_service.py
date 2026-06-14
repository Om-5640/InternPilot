"""Auth business logic — thin layer between the router and the DB.

Rules:
- Duplicate email → 409 (APIError)
- Bad credentials  → 401 (APIError)
- Google id_token verification failures → 401 (propagated from security.verify_google_id_token)
- Refresh token type mismatch / expiry → 401 (propagated from security.decode_token)
- Consent is merged (not replaced) on PUT /auth/consent.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_google_id_token,
    verify_password,
)
from app.models.user import AuthProvider, User, UserRole


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    def _tokens(user: User) -> tuple[str, str]:
        data = {"sub": str(user.id)}
        return create_access_token(data), create_refresh_token(data)

    # -----------------------------------------------------------------------
    # Endpoints
    # -----------------------------------------------------------------------

    async def signup(self, name: str, email: str, password: str) -> tuple[User, str, str]:
        if await self._get_by_email(email):
            raise APIError(409, "EMAIL_TAKEN", "An account with that email already exists")

        user = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.student,
            auth_provider=AuthProvider.password,
            consent={"gmail": False, "github": False, "alumni_data": False},
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        access, refresh = self._tokens(user)
        return user, access, refresh

    async def login(self, email: str, password: str) -> tuple[User, str, str]:
        user = await self._get_by_email(email)
        if not user or not user.password_hash or not verify_password(password, user.password_hash):
            raise APIError(401, "INVALID_CREDENTIALS", "Incorrect email or password")

        access, refresh = self._tokens(user)
        return user, access, refresh

    async def google_login(self, id_token: str) -> tuple[User, str, str]:
        idinfo = await verify_google_id_token(id_token)
        email: str = idinfo["email"]
        name: str = idinfo.get("name", email)

        user = await self._get_by_email(email)
        if user is None:
            user = User(
                name=name,
                email=email,
                password_hash=None,
                role=UserRole.student,
                auth_provider=AuthProvider.google,
                consent={"gmail": False, "github": False, "alumni_data": False},
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)

        access, refresh = self._tokens(user)
        return user, access, refresh

    async def refresh_access_token(self, refresh_token: str) -> str:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise APIError(401, "INVALID_TOKEN", "Token missing subject")
        return create_access_token({"sub": user_id})

    async def update_consent(
        self,
        user: User,
        *,
        gmail: bool | None = None,
        github: bool | None = None,
        alumni_data: bool | None = None,
    ) -> User:
        current: dict[str, bool] = dict(user.consent)  # copy
        if gmail is not None:
            current["gmail"] = gmail
        if github is not None:
            current["github"] = github
        if alumni_data is not None:
            current["alumni_data"] = alumni_data
        user.consent = current
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user
