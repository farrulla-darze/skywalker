"""Unit tests: password hashing and JWT lifecycle."""

import jwt as pyjwt
import pytest

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SETTINGS = Settings(jwt_secret="unit-secret", jwt_expires_minutes=5)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret-password")
    assert hashed != "s3cret-password"
    assert verify_password("s3cret-password", hashed)
    assert not verify_password("wrong", hashed)


def test_verify_password_with_invalid_hash_returns_false():
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_jwt_roundtrip_carries_sub_and_jti():
    token, jti, expires_at = create_access_token(SETTINGS, "user-123")
    payload = decode_access_token(SETTINGS, token)
    assert payload["sub"] == "user-123"
    assert payload["jti"] == jti
    assert expires_at.timestamp() == pytest.approx(payload["exp"], abs=2)


def test_jwt_rejects_wrong_secret():
    token, _, _ = create_access_token(SETTINGS, "user-123")
    other = Settings(jwt_secret="other-secret")
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(other, token)


def test_jwt_rejects_tampered_token():
    token, _, _ = create_access_token(SETTINGS, "user-123")
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(SETTINGS, token[:-4] + "abcd")
