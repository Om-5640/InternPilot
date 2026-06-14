"""Auth router — thin; all logic lives in AuthService."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ConsentUpdateRequest,
    GoogleLoginRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RefreshResponse,
    SignupRequest,
    UserSchema,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth")


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    svc = AuthService(db)
    user, token, refresh_token = await svc.signup(body.name, body.email, body.password)
    return AuthResponse(user=UserSchema.model_validate(user), token=token, refresh_token=refresh_token)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    svc = AuthService(db)
    user, token, refresh_token = await svc.login(body.email, body.password)
    return AuthResponse(user=UserSchema.model_validate(user), token=token, refresh_token=refresh_token)


@router.post("/google", response_model=AuthResponse)
async def google_login(body: GoogleLoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    svc = AuthService(db)
    user, token, refresh_token = await svc.google_login(body.id_token)
    return AuthResponse(user=UserSchema.model_validate(user), token=token, refresh_token=refresh_token)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> RefreshResponse:
    svc = AuthService(db)
    token = await svc.refresh_access_token(body.refresh_token)
    return RefreshResponse(token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: User = Depends(get_current_user)) -> Response:
    # Stateless JWT — token is invalidated client-side.
    # Module 0 does not maintain a token blacklist (no Redis yet).
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user=UserSchema.model_validate(current_user))


@router.put("/consent", response_model=MeResponse)
async def update_consent(
    body: ConsentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    svc = AuthService(db)
    user = await svc.update_consent(
        current_user,
        gmail=body.gmail,
        github=body.github,
        alumni_data=body.alumni_data,
    )
    return MeResponse(user=UserSchema.model_validate(user))
