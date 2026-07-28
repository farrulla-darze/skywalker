"""Support database tools — customer data lookups against the mock support system.

Security note: the customer identifier ALWAYS comes from ``ctx.user_ref``
(the authenticated session), never from LLM-provided parameters. A prompt
injection can therefore never read another customer's data.

The support DB is a SQLite file simulating an external support system;
queries are parameterized (no string interpolation).
"""

import json
import logging
from pathlib import Path

import aiosqlite
from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec

logger = logging.getLogger(__name__)


def _db_path(ctx: ToolRunContext) -> Path:
    return Path(ctx.settings.support_db_path).resolve()


async def _fetch_all(db: aiosqlite.Connection, query: str, params: tuple = ()) -> list[dict]:
    db.row_factory = aiosqlite.Row
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def _fetch_one(db: aiosqlite.Connection, query: str, params: tuple = ()) -> dict | None:
    rows = await _fetch_all(db, query, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# get_customer_overview
# ---------------------------------------------------------------------------


class GetCustomerOverviewParams(BaseModel):
    """No parameters — the customer is the authenticated user of this session."""


async def _get_customer_overview(ctx: ToolRunContext, params: GetCustomerOverviewParams) -> str:
    path = _db_path(ctx)
    if not path.exists():
        return f"Support database not found at {path}"

    user_id = ctx.user_ref
    async with aiosqlite.connect(path) as db:
        user = await _fetch_one(
            db,
            "SELECT id, full_name, email, phone, status, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        if user is None:
            return json.dumps(
                {"user": None, "message": f"No support record found for user '{user_id}'"},
                ensure_ascii=False,
            )

        merchant = await _fetch_one(
            db,
            "SELECT id, user_id, legal_name, trade_name, document, segment, onboarding_status "
            "FROM merchants WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (user_id,),
        )
        products = account = None
        if merchant:
            products = await _fetch_one(
                db,
                "SELECT maquininha, tap_to_pay, pix, boleto, link_pagamento, conta_digital, "
                "emprestimo FROM products_enabled WHERE merchant_id = ?",
                (merchant["id"],),
            )
            account = await _fetch_one(
                db,
                "SELECT balance_available, balance_blocked, transfers_enabled, block_reason, "
                "last_transfer_at FROM account_status WHERE merchant_id = ?",
                (merchant["id"],),
            )
        auth_status = await _fetch_one(
            db,
            "SELECT last_login_at, failed_login_attempts, is_locked, lock_reason "
            "FROM auth_status WHERE user_id = ?",
            (user_id,),
        )

    return json.dumps(
        {
            "user": user,
            "merchant": merchant,
            "products_enabled": products,
            "account_status": account,
            "auth_status": auth_status,
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# get_recent_operations
# ---------------------------------------------------------------------------


class GetRecentOperationsParams(BaseModel):
    limit: int = Field(default=10, ge=1, le=50, description="Max transfers/devices to return")


async def _get_recent_operations(ctx: ToolRunContext, params: GetRecentOperationsParams) -> str:
    path = _db_path(ctx)
    if not path.exists():
        return f"Support database not found at {path}"

    async with aiosqlite.connect(path) as db:
        merchant = await _fetch_one(
            db,
            "SELECT id FROM merchants WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (ctx.user_ref,),
        )
        if merchant is None:
            return json.dumps(
                {"transfers": [], "devices": [],
                 "message": f"No merchant found for user '{ctx.user_ref}'"},
                ensure_ascii=False,
            )

        transfers = await _fetch_all(
            db,
            "SELECT id, amount, status, failure_reason, created_at FROM transfers "
            "WHERE merchant_id = ? ORDER BY created_at DESC LIMIT ?",
            (merchant["id"], params.limit),
        )
        devices = await _fetch_all(
            db,
            "SELECT id, type, model, status, activated_at, last_seen_at FROM devices "
            "WHERE merchant_id = ? ORDER BY COALESCE(last_seen_at, activated_at) DESC LIMIT ?",
            (merchant["id"], params.limit),
        )

    return json.dumps({"transfers": transfers, "devices": devices}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# get_active_incidents
# ---------------------------------------------------------------------------


class GetActiveIncidentsParams(BaseModel):
    """No parameters — returns all currently active platform incidents."""


async def _get_active_incidents(ctx: ToolRunContext, params: GetActiveIncidentsParams) -> str:
    path = _db_path(ctx)
    if not path.exists():
        return f"Support database not found at {path}"

    async with aiosqlite.connect(path) as db:
        incidents = await _fetch_all(
            db,
            "SELECT id, scope, description, started_at FROM incidents "
            "WHERE active = 1 ORDER BY started_at DESC",
        )
    return json.dumps({"incidents": incidents}, ensure_ascii=False, indent=2)


SPECS = [
    ToolSpec(
        name="get_customer_overview",
        label="Customer Overview",
        description=(
            "Get the current customer's support overview: profile, merchant, enabled "
            "products, account status (balance, transfer blocks) and login status. "
            "Applies to the authenticated customer of this conversation."
        ),
        category=ToolCategory.SUPPORT,
        params_model=GetCustomerOverviewParams,
        handler=_get_customer_overview,
    ),
    ToolSpec(
        name="get_recent_operations",
        label="Recent Operations",
        description=(
            "Get the current customer's recent transfers and registered devices."
        ),
        category=ToolCategory.SUPPORT,
        params_model=GetRecentOperationsParams,
        handler=_get_recent_operations,
    ),
    ToolSpec(
        name="get_active_incidents",
        label="Active Incidents",
        description="Get all currently active platform incidents (outages, degradations).",
        category=ToolCategory.SUPPORT,
        params_model=GetActiveIncidentsParams,
        handler=_get_active_incidents,
    ),
]
