"""Auth HTTP layer — parse input, call service, map responses. No business logic here."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.v1.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    SettingsDep,
    get_login_rate_limiter,
)
from app.core.rate_limit import SlidingWindowRateLimiter

from .schemas import LoginRequest, TokenResponse, UserCreate, UserRead
from .service import AuthError

auth_router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer(auto_error=False)


@auth_router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserCreate, service: AuthServiceDep) -> UserRead:
    try:
        return await service.register(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    service: AuthServiceDep,
    settings: SettingsDep,
    limiter: Annotated[SlidingWindowRateLimiter, Depends(get_login_rate_limiter)],
) -> TokenResponse:
    # Rate limit keyed by client IP + target email so one IP can't spray one account
    # and a distributed attempt on a single account is still bounded per source.
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{payload.email.lower()}"
    if not limiter.check(key):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(limiter.retry_after(key))},
        )
    try:
        response = await service.login(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    limiter.reset(key)  # successful login clears the window
    return response


@auth_router.post("/logout", status_code=204)
async def logout(
    service: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        await service.logout(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@auth_router.get("/me", response_model=UserRead)
async def me(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)
