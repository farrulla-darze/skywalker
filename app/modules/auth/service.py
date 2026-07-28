"""Auth business logic."""

import logging
from datetime import UTC, datetime

import jwt as pyjwt

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

from .enums import UserStatus
from .models import User
from .repository import AuthRepository
from .schemas import LoginRequest, TokenResponse, UserCreate, UserRead

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised on authentication/authorization failures (mapped to 401/409 by the API layer)."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthService:
    def __init__(self, repository: AuthRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    async def register(self, payload: UserCreate) -> UserRead:
        existing = await self.repository.get_user_by_email(payload.email.lower())
        if existing:
            raise AuthError("Email already registered", status_code=409)

        user = User(
            email=payload.email.lower(),
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
        )
        user = await self.repository.create_user(user)
        logger.info("User registered: %s", user.email)
        return UserRead.model_validate(user)

    async def login(self, payload: LoginRequest) -> TokenResponse:
        user = await self.repository.get_user_by_email(payload.email.lower())
        # Unknown email and wrong password intentionally return the same generic error.
        if user is None or not verify_password(payload.password, user.password_hash):
            raise AuthError("Invalid email or password")
        if user.status != UserStatus.ACTIVE:
            raise AuthError("Account disabled")

        token, _jti, expires_at = create_access_token(self.settings, user.id)
        return TokenResponse(
            access_token=token, expires_at=expires_at, user=UserRead.model_validate(user)
        )

    async def logout(self, token: str) -> None:
        """Invalidate the presented JWT by adding its jti to the denylist."""
        try:
            payload = decode_access_token(self.settings, token)
        except pyjwt.PyJWTError as exc:
            raise AuthError("Invalid token") from exc

        expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
        await self.repository.revoke_token(payload["jti"], payload["sub"], expires_at)

    async def resolve_user(self, token: str) -> User:
        """Validate a JWT (signature, expiry, revocation) and return its user."""
        try:
            payload = decode_access_token(self.settings, token)
        except pyjwt.ExpiredSignatureError as exc:
            raise AuthError("Token expired") from exc
        except pyjwt.PyJWTError as exc:
            raise AuthError("Invalid token") from exc

        if await self.repository.is_token_revoked(payload["jti"]):
            raise AuthError("Token revoked")

        user = await self.repository.get_user_by_id(payload["sub"])
        if user is None or user.status != UserStatus.ACTIVE:
            raise AuthError("User not found or disabled")
        return user
