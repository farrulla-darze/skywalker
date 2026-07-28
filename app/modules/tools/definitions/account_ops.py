"""Account write tools — mutations on the support database.

Governance model: these tools EXECUTE changes but do not decide them. The
authorization comes from a prior ``consult_human`` round in the same
conversation; the Account Operations agent's instructions require the router
to state that human authorization was granted before any write is delegated.

Security: like the read tools, the target account is ALWAYS resolved from
``ctx.user_ref`` (authenticated session) — never from LLM-chosen parameters.
Every write returns an explicit before/after snapshot for the trace.
"""

import json
import logging
from typing import Literal

import aiosqlite
from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec
from .support_db import _db_path, _fetch_one

logger = logging.getLogger(__name__)

# Whitelisted product columns in products_enabled (guards against injection —
# the column name is taken from this literal, never from free text).
ProductName = Literal[
    "maquininha", "tap_to_pay", "pix", "boleto", "link_pagamento", "conta_digital", "emprestimo"
]


async def _merchant_id_for(ctx: ToolRunContext, db: aiosqlite.Connection) -> str | None:
    row = await _fetch_one(
        db,
        "SELECT id FROM merchants WHERE user_id = ? ORDER BY id ASC LIMIT 1",
        (ctx.user_ref,),
    )
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# release_transfer
# ---------------------------------------------------------------------------


class ReleaseTransferParams(BaseModel):
    transfer_id: str = Field(description="Id of the blocked transfer to release, e.g. 'txf_far_001'")


async def _release_transfer(ctx: ToolRunContext, params: ReleaseTransferParams) -> str:
    path = _db_path(ctx)
    if not path.exists():
        return f"Support database not found at {path}"

    async with aiosqlite.connect(path) as db:
        merchant_id = await _merchant_id_for(ctx, db)
        if merchant_id is None:
            return f"No merchant found for the authenticated customer '{ctx.user_ref}'."

        before = await _fetch_one(
            db,
            "SELECT id, amount, status, failure_reason, created_at FROM transfers "
            "WHERE id = ? AND merchant_id = ?",
            (params.transfer_id, merchant_id),
        )
        if before is None:
            return (
                f"Transfer '{params.transfer_id}' not found on this customer's account — "
                "verify the id with get_recent_operations."
            )
        if before["status"] != "blocked":
            return (
                f"Transfer '{params.transfer_id}' is not blocked "
                f"(current status: {before['status']}) — nothing to release."
            )

        await db.execute(
            "UPDATE transfers SET status = 'completed', failure_reason = NULL WHERE id = ?",
            (params.transfer_id,),
        )
        await db.commit()
        after = await _fetch_one(
            db,
            "SELECT id, amount, status, failure_reason, created_at FROM transfers WHERE id = ?",
            (params.transfer_id,),
        )

    logger.info("Transfer released: %s (user %s)", params.transfer_id, ctx.user_ref)
    return json.dumps({"released": True, "before": before, "after": after}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# set_transfers_enabled
# ---------------------------------------------------------------------------


class SetTransfersEnabledParams(BaseModel):
    enabled: bool = Field(description="True to unblock outgoing transfers, False to block")
    reason: str | None = Field(
        default=None,
        description="Required when blocking: the block_reason to record (e.g. 'fraud_review')",
    )


async def _set_transfers_enabled(ctx: ToolRunContext, params: SetTransfersEnabledParams) -> str:
    if not params.enabled and not params.reason:
        return "Blocking transfers requires a reason — provide the block_reason."
    path = _db_path(ctx)
    if not path.exists():
        return f"Support database not found at {path}"

    async with aiosqlite.connect(path) as db:
        merchant_id = await _merchant_id_for(ctx, db)
        if merchant_id is None:
            return f"No merchant found for the authenticated customer '{ctx.user_ref}'."

        before = await _fetch_one(
            db,
            "SELECT transfers_enabled, block_reason FROM account_status WHERE merchant_id = ?",
            (merchant_id,),
        )
        await db.execute(
            "UPDATE account_status SET transfers_enabled = ?, block_reason = ? "
            "WHERE merchant_id = ?",
            (1 if params.enabled else 0, None if params.enabled else params.reason, merchant_id),
        )
        await db.commit()
        after = await _fetch_one(
            db,
            "SELECT transfers_enabled, block_reason FROM account_status WHERE merchant_id = ?",
            (merchant_id,),
        )

    logger.info(
        "transfers_enabled=%s for merchant %s (user %s)",
        params.enabled, merchant_id, ctx.user_ref,
    )
    return json.dumps({"updated": True, "before": before, "after": after}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# set_product_enabled
# ---------------------------------------------------------------------------


class SetProductEnabledParams(BaseModel):
    product: ProductName = Field(description="Which product to toggle for this merchant")
    enabled: bool = Field(description="True to enable the product, False to disable")


async def _set_product_enabled(ctx: ToolRunContext, params: SetProductEnabledParams) -> str:
    path = _db_path(ctx)
    if not path.exists():
        return f"Support database not found at {path}"

    column = params.product  # constrained by the ProductName Literal whitelist
    async with aiosqlite.connect(path) as db:
        merchant_id = await _merchant_id_for(ctx, db)
        if merchant_id is None:
            return f"No merchant found for the authenticated customer '{ctx.user_ref}'."

        before = await _fetch_one(
            db, f"SELECT {column} FROM products_enabled WHERE merchant_id = ?", (merchant_id,)
        )
        await db.execute(
            f"UPDATE products_enabled SET {column} = ? WHERE merchant_id = ?",
            (1 if params.enabled else 0, merchant_id),
        )
        await db.commit()
        after = await _fetch_one(
            db, f"SELECT {column} FROM products_enabled WHERE merchant_id = ?", (merchant_id,)
        )

    logger.info(
        "product %s=%s for merchant %s (user %s)",
        column, params.enabled, merchant_id, ctx.user_ref,
    )
    return json.dumps(
        {"updated": True, "product": column, "before": before, "after": after}, ensure_ascii=False
    )


SPECS = [
    ToolSpec(
        name="release_transfer",
        label="Release Blocked Transfer",
        description=(
            "EXECUTE the release of a blocked transfer on the authenticated customer's "
            "account (status blocked → completed). Only use when the instruction states "
            "that a human specialist already authorized the release via consultation. "
            "Returns a before/after snapshot."
        ),
        category=ToolCategory.ACTION,
        params_model=ReleaseTransferParams,
        handler=_release_transfer,
    ),
    ToolSpec(
        name="set_transfers_enabled",
        label="Enable/Block Account Transfers",
        description=(
            "EXECUTE enabling or blocking of outgoing transfers on the authenticated "
            "customer's account (account_status.transfers_enabled + block_reason). Only "
            "use with stated human authorization. Returns a before/after snapshot."
        ),
        category=ToolCategory.ACTION,
        params_model=SetTransfersEnabledParams,
        handler=_set_transfers_enabled,
    ),
    ToolSpec(
        name="set_product_enabled",
        label="Enable/Disable Product",
        description=(
            "EXECUTE enabling or disabling of a product (maquininha, pix, boleto, etc.) "
            "for the authenticated customer's merchant. Only use with stated human "
            "authorization. Returns a before/after snapshot."
        ),
        category=ToolCategory.ACTION,
        params_model=SetProductEnabledParams,
        handler=_set_product_enabled,
    ),
]
