"""Live integration tests for support_db tools using local SQLite data.

This test module runs tools directly (no agent orchestration) and validates
that each tool returns the expected payload structure.

Usage as standalone script:
    python tests/integration/test_support_db_tools_live.py
    python tests/integration/test_support_db_tools_live.py --user-id client789 --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.modules.tools.support_db import (
    DB_PATH,
    create_get_active_incidents_tool,
    create_get_customer_overview_tool,
    create_get_recent_operations_tool,
)
from src.modules.tools.schema import (
    GetActiveIncidentsParams,
    GetCustomerOverviewParams,
    GetRecentOperationsParams,
)


def _details_as_dict(details) -> dict:
    """Normalize ToolResult.details to a plain dict for assertions/printing."""
    if details is None:
        return {}
    if isinstance(details, dict):
        return details
    if hasattr(details, "model_dump"):
        return details.model_dump(exclude_none=True)
    return {}


def _parse_json_content(result) -> dict:
    """Parse first text content block as JSON payload."""
    assert result.content, "Expected content blocks in ToolResult"
    text = result.content[0].text
    return json.loads(text)


def _print_tool_result(tool_name: str, payload: dict, details: dict) -> None:
    """Pretty-print tool execution output for comprehensive debugging."""
    print("\n" + "=" * 80)
    print(f"TOOL: {tool_name}")
    print("=" * 80)
    print("PAYLOAD:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nDETAILS:")
    print(json.dumps(details, ensure_ascii=False, indent=2))
    print("=" * 80)


@pytest.mark.asyncio
async def test_get_customer_overview_returns_expected_sections():
    """Validate get_customer_overview returns all required domain sections."""
    if not DB_PATH.exists():
        pytest.skip(f"support.db not found at {DB_PATH}")

    tool = create_get_customer_overview_tool()
    params = GetCustomerOverviewParams(user_id="client789")

    result = await tool.execute("integration-customer-overview", params)
    payload = _parse_json_content(result)
    details = _details_as_dict(result.details)

    _print_tool_result("get_customer_overview", payload, details)

    for key in ["user", "merchant", "products_enabled", "account_status", "auth_status"]:
        assert key in payload, f"Missing key '{key}' in get_customer_overview output"

    assert payload["user"] is not None
    assert payload["user"]["id"] == "client789"
    assert payload["merchant"] is not None
    assert payload["merchant"]["user_id"] == "client789"


@pytest.mark.asyncio
async def test_get_recent_operations_returns_transfers_and_devices():
    """Validate get_recent_operations returns transfers and devices respecting limit."""
    if not DB_PATH.exists():
        pytest.skip(f"support.db not found at {DB_PATH}")

    tool = create_get_recent_operations_tool()
    params = GetRecentOperationsParams(user_id="client789", limit=10)

    result = await tool.execute("integration-recent-operations", params)
    payload = _parse_json_content(result)
    details = _details_as_dict(result.details)

    _print_tool_result("get_recent_operations", payload, details)

    assert "transfers" in payload, "Missing 'transfers' key"
    assert "devices" in payload, "Missing 'devices' key"
    assert isinstance(payload["transfers"], list)
    assert isinstance(payload["devices"], list)
    assert len(payload["transfers"]) <= 10
    assert len(payload["devices"]) <= 10


@pytest.mark.asyncio
async def test_get_active_incidents_returns_active_incidents_list():
    """Validate get_active_incidents returns incident list with active entries."""
    if not DB_PATH.exists():
        pytest.skip(f"support.db not found at {DB_PATH}")

    tool = create_get_active_incidents_tool()
    params = GetActiveIncidentsParams()

    result = await tool.execute("integration-active-incidents", params)
    payload = _parse_json_content(result)
    details = _details_as_dict(result.details)

    _print_tool_result("get_active_incidents", payload, details)

    assert "incidents" in payload, "Missing 'incidents' key"
    assert isinstance(payload["incidents"], list)
    assert len(payload["incidents"]) >= 1, "Expected at least one active incident"
    assert all(item.get("active") == 1 for item in payload["incidents"])


async def run_standalone(user_id: str, limit: int) -> int:
    """Run all support DB tools and print comprehensive output for each one."""
    print("\n" + "=" * 80)
    print("SUPPORT DB TOOLS - STANDALONE INTEGRATION TEST")
    print("=" * 80)
    print(f"DB Path: {DB_PATH}")
    print(f"User ID: {user_id}")
    print(f"Limit: {limit}")

    if not DB_PATH.exists():
        print(f"\n❌ ERROR: support.db not found at {DB_PATH}")
        print("Run: python db/support_db/init_db.py")
        return 1

    try:
        overview_tool = create_get_customer_overview_tool()
        recent_tool = create_get_recent_operations_tool()
        incidents_tool = create_get_active_incidents_tool()

        overview_result = await overview_tool.execute(
            "standalone-customer-overview",
            GetCustomerOverviewParams(user_id=user_id),
        )
        overview_payload = _parse_json_content(overview_result)
        _print_tool_result(
            "get_customer_overview",
            overview_payload,
            _details_as_dict(overview_result.details),
        )

        recent_result = await recent_tool.execute(
            "standalone-recent-operations",
            GetRecentOperationsParams(user_id=user_id, limit=limit),
        )
        recent_payload = _parse_json_content(recent_result)
        _print_tool_result(
            "get_recent_operations",
            recent_payload,
            _details_as_dict(recent_result.details),
        )

        incidents_result = await incidents_tool.execute(
            "standalone-active-incidents",
            GetActiveIncidentsParams(),
        )
        incidents_payload = _parse_json_content(incidents_result)
        _print_tool_result(
            "get_active_incidents",
            incidents_payload,
            _details_as_dict(incidents_result.details),
        )

        print("\n✅ All support DB tools executed successfully")
        return 0
    except Exception as exc:
        print(f"\n❌ ERROR: {exc}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run integration checks for support_db tools directly (without agent)",
    )
    parser.add_argument(
        "--user-id",
        default="client789",
        help="User ID to use for customer overview and recent operations (default: client789)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Limit for recent operations (default: 10)",
    )
    parser.add_argument(
        "--pytest",
        action="store_true",
        help="Run pytest for this file instead of standalone mode",
    )

    args = parser.parse_args()

    if args.pytest:
        raise SystemExit(pytest.main([__file__, "-v", "-s"]))

    exit_code = asyncio.run(run_standalone(user_id=args.user_id, limit=args.limit))
    raise SystemExit(exit_code)
