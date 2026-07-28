"""API tests: registration, login, JWT revocation on logout, login rate limit."""

import pytest

pytestmark = pytest.mark.anyio


REGISTER = {"email": "user@example.com", "full_name": "User", "password": "secret123"}


async def test_register_login_me_flow(client):
    response = await client.post("/api/v1/auth/register", json=REGISTER)
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "user@example.com"

    response = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "secret123"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"


async def test_register_duplicate_email_conflicts(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post("/api/v1/auth/register", json=REGISTER)
    assert response.status_code == 409


async def test_login_wrong_password_is_generic_401(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong-pass"}
    )
    assert response.status_code == 401
    # Same error for unknown email (no user enumeration)
    response2 = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "whatever1"}
    )
    assert response2.status_code == 401
    assert response.json()["detail"] == response2.json()["detail"]


async def test_logout_revokes_token(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "secret123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    # Same token must now be rejected (denylist)
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_login_rate_limit_returns_429(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    bad = {"email": "user@example.com", "password": "wrong-pass"}
    # test settings allow 3 attempts per window
    for _ in range(3):
        response = await client.post("/api/v1/auth/login", json=bad)
        assert response.status_code == 401
    response = await client.post("/api/v1/auth/login", json=bad)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


async def test_protected_routes_require_token(client):
    assert (await client.get("/api/v1/agents")).status_code == 401
    assert (await client.get("/api/v1/tools")).status_code == 401
    assert (await client.get("/api/v1/chat/sessions")).status_code == 401
