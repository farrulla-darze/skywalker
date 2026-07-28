"""API tests: chat pipeline end-to-end with pydantic-ai's TestModel (no real LLM).

Covers both challenge payload shapes on POST /chat, session continuity,
steps persistence and message feedback.
"""

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app
from tests.conftest import TEST_SETTINGS

pytestmark = pytest.mark.anyio


@pytest.fixture
async def chat_client():
    """App wired to the TestModel so the full agent loop runs without an LLM."""
    settings = TEST_SETTINGS.model_copy(update={"default_model": "test"})
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


async def _register_and_login(client) -> dict:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "chat@example.com", "full_name": "Chat", "password": "secret123"},
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": "chat@example.com", "password": "secret123"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_legacy_chat_accepts_challenge_payload_shape(chat_client):
    response = await chat_client.post(
        "/chat", json={"message": "What are the fees?", "user_id": "client789"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sessionId"]
    assert isinstance(body["response"], str) and body["response"]
    assert "total_tokens" in body["metadata"]


async def test_legacy_chat_accepts_v1_payload_shape(chat_client):
    response = await chat_client.post(
        "/chat", json={"question": "What are the fees?", "userId": "client789"}
    )
    assert response.status_code == 200, response.text


async def test_legacy_chat_session_continuity(chat_client):
    first = await chat_client.post("/chat", json={"message": "hi", "user_id": "u1"})
    session_id = first.json()["sessionId"]
    second = await chat_client.post(
        "/chat", json={"message": "again", "user_id": "u1", "sessionId": session_id}
    )
    assert second.json()["sessionId"] == session_id


async def test_authenticated_chat_flow_with_steps_and_feedback(chat_client):
    headers = await _register_and_login(chat_client)

    created = await chat_client.post("/api/v1/chat/sessions", json={}, headers=headers)
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    sent = await chat_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Are there active incidents?"},
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    assistant = sent.json()
    assert assistant["role"] == "assistant"
    assert assistant["usage"]["input_tokens"] > 0

    messages = await chat_client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=headers
    )
    assert messages.status_code == 200
    roles = [m["role"] for m in messages.json()]
    assert roles[0] == "user" and roles[-1] == "assistant"

    feedback = await chat_client.post(
        f"/api/v1/chat/messages/{assistant['id']}/feedback",
        json={"rating": "down", "comment": "resposta incompleta"},
        headers=headers,
    )
    assert feedback.status_code == 204

    # Feedback shows up on re-read
    messages = await chat_client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=headers
    )
    last = messages.json()[-1]
    assert last["feedback"] == {"rating": "down", "comment": "resposta incompleta"}


async def test_user_cannot_read_another_users_session(chat_client):
    headers_a = await _register_and_login(chat_client)
    created = await chat_client.post("/api/v1/chat/sessions", json={}, headers=headers_a)
    session_id = created.json()["id"]

    await chat_client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "full_name": "Other", "password": "secret123"},
    )
    login = await chat_client.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": "secret123"}
    )
    headers_b = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = await chat_client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=headers_b
    )
    assert response.status_code == 404


async def test_golden_dataset_seeded_and_promotion_flow(chat_client):
    headers = await _register_and_login(chat_client)
    items = await chat_client.get("/api/v1/evaluation/golden-items", headers=headers)
    assert items.status_code == 200
    questions = [i["question"] for i in items.json()]
    # The 8 challenge scenarios must be present
    assert "What's the difference between the Get Clássica and the Get Smart?" in questions
    assert "What's the euro exchange rate today?" in questions

    # Promote a chat answer into a golden item draft
    created = await chat_client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = created.json()["id"]
    sent = await chat_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "How do fees work?"},
        headers=headers,
    )
    message_id = sent.json()["id"]
    promoted = await chat_client.post(
        "/api/v1/evaluation/golden-items/promote",
        json={"message_id": message_id},
        headers=headers,
    )
    assert promoted.status_code == 201, promoted.text
    assert promoted.json()["question"] == "How do fees work?"
    assert promoted.json()["provenance"] == "production_trace"


async def test_streaming_endpoint_emits_tokens_and_done(chat_client):
    headers = await _register_and_login(chat_client)
    created = await chat_client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = created.json()["id"]

    events = []
    async with chat_client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages/stream",
        json={"content": "hello streaming"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        import json as _json

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(_json.loads(line[len("data: "):]))

    types = [e["type"] for e in events]
    assert "token" in types, f"expected token events, got {types}"
    assert types[-1] == "done"
    done = events[-1]["message"]
    assert done["role"] == "assistant"
    assert done["content"]
    # streamed deltas must reconstruct the persisted message
    streamed = "".join(e["delta"] for e in events if e["type"] == "token")
    assert streamed == done["content"]
