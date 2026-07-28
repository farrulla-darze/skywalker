"""Shared FastAPI dependencies: settings, current user, rate limiter."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.rate_limit import SlidingWindowRateLimiter
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthError, AuthService

_bearer = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_login_rate_limiter(request: Request) -> SlidingWindowRateLimiter:
    return request.app.state.login_rate_limiter


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(AuthRepository(session), settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    auth_service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return await auth_service.resolve_user(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    auth_service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    """Like get_current_user but returns None for anonymous requests (legacy /chat)."""
    if credentials is None:
        return None
    try:
        return await auth_service.resolve_user(credentials.credentials)
    except AuthError:
        return None
