"""Support DB tools - Query local SQLite support database for customer operations."""

import json
import sqlite3
from pathlib import Path
from threading import Event
from typing import Optional

from .schema import (
    AgentTool,
    GetActiveIncidentsParams,
    GetCustomerOverviewParams,
    GetRecentOperationsParams,
    TextContent,
    ToolResult,
)

DB_PATH = Path(__file__).resolve().parents[3] / "db" / "support_db" / "support.db"


def _get_connection() -> sqlite3.Connection:
    """Create SQLite connection with row factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    """Convert sqlite row to plain dict."""
    if row is None:
        return None
    return dict(row)


async def _execute_get_customer_overview(
    tool_call_id: str,
    params: GetCustomerOverviewParams,
    signal: Optional[Event] = None,
) -> ToolResult:
    """Fetch user, merchant, products, account and auth support overview."""
    if signal and signal.is_set():
        raise Exception("Operation aborted")

    if not DB_PATH.exists():
        return ToolResult(
            content=[TextContent(text=f"support.db not found at: {DB_PATH}")],
            details={"db_path": str(DB_PATH), "error": "db_not_found"},
        )

    try:
        with _get_connection() as conn:
            user_row = conn.execute(
                "SELECT id, full_name, email, phone, status, created_at FROM users WHERE id = ?",
                (params.user_id,),
            ).fetchone()

            if user_row is None:
                payload = {
                    "user": None,
                    "merchant": None,
                    "products_enabled": None,
                    "account_status": None,
                    "auth_status": None,
                    "message": f"No user found for user_id '{params.user_id}'",
                }
                return ToolResult(
                    content=[TextContent(text=json.dumps(payload, ensure_ascii=False, indent=2))],
                    details={"user_id": params.user_id, "found": False},
                )

            merchant_row = conn.execute(
                """
                SELECT id, user_id, legal_name, trade_name, document, segment, onboarding_status
                FROM merchants
                WHERE user_id = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (params.user_id,),
            ).fetchone()

            merchant_id = merchant_row["id"] if merchant_row else None

            products_row = None
            account_row = None
            if merchant_id:
                products_row = conn.execute(
                    """
                    SELECT merchant_id, maquininha, tap_to_pay, pix, boleto,
                           link_pagamento, conta_digital, emprestimo
                    FROM products_enabled
                    WHERE merchant_id = ?
                    """,
                    (merchant_id,),
                ).fetchone()

                account_row = conn.execute(
                    """
                    SELECT merchant_id, balance_available, balance_blocked,
                           transfers_enabled, block_reason, last_transfer_at
                    FROM account_status
                    WHERE merchant_id = ?
                    """,
                    (merchant_id,),
                ).fetchone()

            auth_row = conn.execute(
                """
                SELECT user_id, last_login_at, failed_login_attempts, is_locked, lock_reason
                FROM auth_status
                WHERE user_id = ?
                """,
                (params.user_id,),
            ).fetchone()

            payload = {
                "user": _row_to_dict(user_row),
                "merchant": _row_to_dict(merchant_row),
                "products_enabled": _row_to_dict(products_row),
                "account_status": _row_to_dict(account_row),
                "auth_status": _row_to_dict(auth_row),
            }

            return ToolResult(
                content=[TextContent(text=json.dumps(payload, ensure_ascii=False, indent=2))],
                details={
                    "user_id": params.user_id,
                    "merchant_found": merchant_row is not None,
                },
            )
    except Exception as exc:
        return ToolResult(
            content=[TextContent(text=f"Failed to fetch customer overview: {exc}")],
            details={"user_id": params.user_id, "error": str(exc)},
        )


async def _execute_get_recent_operations(
    tool_call_id: str,
    params: GetRecentOperationsParams,
    signal: Optional[Event] = None,
) -> ToolResult:
    """Fetch recent transfers and devices for the user's merchant account."""
    if signal and signal.is_set():
        raise Exception("Operation aborted")

    if not DB_PATH.exists():
        return ToolResult(
            content=[TextContent(text=f"support.db not found at: {DB_PATH}")],
            details={"db_path": str(DB_PATH), "error": "db_not_found"},
        )

    try:
        with _get_connection() as conn:
            merchant_row = conn.execute(
                "SELECT id FROM merchants WHERE user_id = ? ORDER BY id ASC LIMIT 1",
                (params.user_id,),
            ).fetchone()

            if merchant_row is None:
                payload = {
                    "transfers": [],
                    "devices": [],
                    "message": f"No merchant found for user_id '{params.user_id}'",
                }
                return ToolResult(
                    content=[TextContent(text=json.dumps(payload, ensure_ascii=False, indent=2))],
                    details={"user_id": params.user_id, "found": False},
                )

            merchant_id = merchant_row["id"]

            transfer_rows = conn.execute(
                """
                SELECT id, merchant_id, amount, status, failure_reason, created_at
                FROM transfers
                WHERE merchant_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (merchant_id, params.limit),
            ).fetchall()

            device_rows = conn.execute(
                """
                SELECT id, merchant_id, type, model, status, activated_at, last_seen_at
                FROM devices
                WHERE merchant_id = ?
                ORDER BY COALESCE(last_seen_at, activated_at) DESC
                LIMIT ?
                """,
                (merchant_id, params.limit),
            ).fetchall()

            payload = {
                "transfers": [_row_to_dict(row) for row in transfer_rows],
                "devices": [_row_to_dict(row) for row in device_rows],
            }

            return ToolResult(
                content=[TextContent(text=json.dumps(payload, ensure_ascii=False, indent=2))],
                details={
                    "user_id": params.user_id,
                    "merchant_id": merchant_id,
                    "limit": params.limit,
                    "transfer_count": len(transfer_rows),
                    "device_count": len(device_rows),
                },
            )
    except Exception as exc:
        return ToolResult(
            content=[TextContent(text=f"Failed to fetch recent operations: {exc}")],
            details={"user_id": params.user_id, "error": str(exc)},
        )


async def _execute_get_active_incidents(
    tool_call_id: str,
    params: GetActiveIncidentsParams,
    signal: Optional[Event] = None,
) -> ToolResult:
    """Fetch currently active incidents from support DB."""
    if signal and signal.is_set():
        raise Exception("Operation aborted")

    if not DB_PATH.exists():
        return ToolResult(
            content=[TextContent(text=f"support.db not found at: {DB_PATH}")],
            details={"db_path": str(DB_PATH), "error": "db_not_found"},
        )

    try:
        with _get_connection() as conn:
            incident_rows = conn.execute(
                """
                SELECT id, scope, active, description, started_at
                FROM incidents
                WHERE active = 1
                ORDER BY started_at DESC
                """
            ).fetchall()

            payload = {
                "incidents": [_row_to_dict(row) for row in incident_rows],
            }

            return ToolResult(
                content=[TextContent(text=json.dumps(payload, ensure_ascii=False, indent=2))],
                details={"active_incidents_count": len(incident_rows)},
            )
    except Exception as exc:
        return ToolResult(
            content=[TextContent(text=f"Failed to fetch active incidents: {exc}")],
            details={"error": str(exc)},
        )


def create_get_customer_overview_tool() -> AgentTool:
    """Create support-db tool for customer consolidated overview."""

    async def execute(
        tool_call_id: str,
        params: GetCustomerOverviewParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        return await _execute_get_customer_overview(tool_call_id, params, signal)

    return AgentTool(
        name="get_customer_overview",
        label="get_customer_overview",
        description=(
            "Get full support overview for a user_id from support.db, returning "
            "user, merchant, products_enabled, account_status, and auth_status."
        ),
        parameters_schema=GetCustomerOverviewParams,
        execute=execute,
    )


def create_get_recent_operations_tool() -> AgentTool:
    """Create support-db tool for recent transfers and devices."""

    async def execute(
        tool_call_id: str,
        params: GetRecentOperationsParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        return await _execute_get_recent_operations(tool_call_id, params, signal)

    return AgentTool(
        name="get_recent_operations",
        label="get_recent_operations",
        description=(
            "Get recent operational history for a user_id from support.db, "
            "returning transfers and devices."
        ),
        parameters_schema=GetRecentOperationsParams,
        execute=execute,
    )


def create_get_active_incidents_tool() -> AgentTool:
    """Create support-db tool for active incidents."""

    async def execute(
        tool_call_id: str,
        params: GetActiveIncidentsParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        return await _execute_get_active_incidents(tool_call_id, params, signal)

    return AgentTool(
        name="get_active_incidents",
        label="get_active_incidents",
        description=(
            "Get all active platform incidents from support.db. "
            "Returns incidents currently marked as active."
        ),
        parameters_schema=GetActiveIncidentsParams,
        execute=execute,
    )
