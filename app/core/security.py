"""Password hashing and JWT creation/verification.

JWTs carry a ``jti`` claim so individual tokens can be revoked at logout
(denylist persisted in the ``revoked_tokens`` table — see the auth module).
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from .config import Settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(settings: Settings, user_id: str) -> tuple[str, str, datetime]:
    """Create a signed JWT for *user_id*.

    Returns:
        Tuple of (token, jti, expires_at).
    """
    jti = uuid.uuid4().hex
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expires_minutes)
    payload = {
        "sub": user_id,
        "jti": jti,
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at


def decode_access_token(settings: Settings, token: str) -> dict:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on any failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
