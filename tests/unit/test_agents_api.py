"""API tests: agent CRUD backed by the database, tool catalog validation, seeds."""

import pytest

pytestmark = pytest.mark.anyio


async def test_system_agents_are_seeded(client, auth_headers):
    response = await client.get("/api/v1/agents", headers=auth_headers)
    assert response.status_code == 200
    slugs = {a["slug"] for a in response.json()}
    assert {"sky-router", "customer-support"} <= slugs


async def test_tool_catalog_is_exposed(client, auth_headers):
    response = await client.get("/api/v1/tools", headers=auth_headers)
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert {
        "rag_search",
        "web_search",
        "graph_search",
        "get_customer_overview",
        "get_recent_operations",
        "get_active_incidents",
        "escalate_to_human",
    } <= names


async def test_create_update_delete_agent(client, auth_headers):
    payload = {
        "name": "Billing Agent",
        "slug": "billing-agent",
        "description": "Handles billing questions",
        "instructions": "You answer billing questions.",
        "tools": ["rag_search"],
    }
    response = await client.post("/api/v1/agents", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["tools"] == ["rag_search"]
    assert agent["is_system"] is False

    response = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        json={"enabled": False, "tools": ["rag_search", "web_search"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["tools"] == ["rag_search", "web_search"]

    response = await client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
    assert response.status_code == 204


async def test_create_agent_with_unknown_tool_fails(client, auth_headers):
    payload = {
        "name": "Bad",
        "slug": "bad-agent",
        "instructions": "x",
        "tools": ["nonexistent_tool"],
    }
    response = await client.post("/api/v1/agents", json=payload, headers=auth_headers)
    assert response.status_code == 400
    assert "nonexistent_tool" in response.json()["detail"]


async def test_duplicate_slug_conflicts(client, auth_headers):
    payload = {"name": "A", "slug": "dup-agent", "instructions": "x"}
    assert (
        await client.post("/api/v1/agents", json=payload, headers=auth_headers)
    ).status_code == 201
    assert (
        await client.post("/api/v1/agents", json=payload, headers=auth_headers)
    ).status_code == 409


async def test_system_agent_cannot_be_deleted(client, auth_headers):
    agents = (await client.get("/api/v1/agents", headers=auth_headers)).json()
    router = next(a for a in agents if a["slug"] == "sky-router")
    response = await client.delete(f"/api/v1/agents/{router['id']}", headers=auth_headers)
    assert response.status_code == 400
