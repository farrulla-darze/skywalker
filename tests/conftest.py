"""Shared test fixtures: in-memory app with SQLite, no external services."""

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.main import create_app

TEST_SETTINGS = Settings(
    environment="test",
    database_url="sqlite+aiosqlite://",  # in-memory
    jwt_secret="test-secret",
    jwt_expires_minutes=60,
    login_rate_limit_attempts=3,
    login_rate_limit_window_seconds=60,
    guardrails_enabled=False,
    graph_enabled=False,
    langfuse_enabled=False,  # pinned: must not inherit LANGFUSE_ENABLED=true from .env
    allow_anonymous_chat=True,
    support_db_path="db/support_db/support.db",
    openai_api_key="test-key-not-used",
)


@pytest.fixture
def test_settings() -> Settings:
    return TEST_SETTINGS.model_copy()


@pytest.fixture
async def client(test_settings):
    """Async HTTP client against a fresh app instance (lifespan included)."""
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


@pytest.fixture
async def auth_headers(client):
    """Register + login a user, return Authorization headers."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "tester@example.com", "full_name": "Tester", "password": "secret123"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "tester@example.com", "password": "secret123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
