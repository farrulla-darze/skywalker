"""Tests: account write tools — scoping, guards and before/after reporting."""

import json
import sqlite3

import pytest

from app.core.config import Settings
from app.modules.tools.definitions.account_ops import (
    ReleaseTransferParams,
    SetProductEnabledParams,
    SetTransfersEnabledParams,
    _release_transfer,
    _set_product_enabled,
    _set_transfers_enabled,
)
from app.modules.tools.service import ToolRunContext

pytestmark = pytest.mark.anyio


@pytest.fixture
def support_db(tmp_path):
    path = tmp_path / "support.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE merchants (id TEXT PRIMARY KEY, user_id TEXT);
        CREATE TABLE transfers (
            id TEXT PRIMARY KEY, merchant_id TEXT, amount REAL,
            status TEXT, failure_reason TEXT, created_at TEXT
        );
        CREATE TABLE account_status (
            merchant_id TEXT PRIMARY KEY, balance_available REAL, balance_blocked REAL,
            transfers_enabled INTEGER, block_reason TEXT, last_transfer_at TEXT
        );
        CREATE TABLE products_enabled (merchant_id TEXT PRIMARY KEY, pix INTEGER, boleto INTEGER,
            maquininha INTEGER, tap_to_pay INTEGER, link_pagamento INTEGER,
            conta_digital INTEGER, emprestimo INTEGER);
        INSERT INTO merchants VALUES ('m1', 'user-a'), ('m2', 'user-b');
        INSERT INTO transfers VALUES
            ('t1', 'm1', 1200.0, 'blocked', 'compliance_hold', '2026-07-24'),
            ('t2', 'm1', 500.0, 'completed', NULL, '2026-07-20'),
            ('t3', 'm2', 900.0, 'blocked', 'fraud_review', '2026-07-25');
        INSERT INTO account_status VALUES ('m1', 8750.0, 1200.0, 0, 'compliance_review', NULL);
        INSERT INTO products_enabled VALUES ('m1', 1, 1, 1, 1, 1, 1, 0);
        """
    )
    conn.commit()
    conn.close()
    return path


def make_ctx(support_db, user_ref="user-a") -> ToolRunContext:
    settings = Settings(langfuse_enabled=False, support_db_path=str(support_db))
    return ToolRunContext(settings=settings, user_ref=user_ref, session_id="s1")


async def test_release_transfer_happy_path_reports_before_after(support_db):
    result = json.loads(
        await _release_transfer(make_ctx(support_db), ReleaseTransferParams(transfer_id="t1"))
    )
    assert result["released"] is True
    assert result["before"]["status"] == "blocked"
    assert result["after"]["status"] == "completed"
    assert result["after"]["failure_reason"] is None


async def test_release_transfer_scoped_to_authenticated_customer(support_db):
    # t3 belongs to user-b's merchant — user-a must not be able to touch it
    result = await _release_transfer(make_ctx(support_db), ReleaseTransferParams(transfer_id="t3"))
    assert "not found" in result
    # And it stayed blocked
    conn = sqlite3.connect(support_db)
    assert conn.execute("SELECT status FROM transfers WHERE id='t3'").fetchone()[0] == "blocked"


async def test_release_transfer_refuses_non_blocked(support_db):
    result = await _release_transfer(make_ctx(support_db), ReleaseTransferParams(transfer_id="t2"))
    assert "not blocked" in result


async def test_set_transfers_enabled_unblock_clears_reason(support_db):
    result = json.loads(
        await _set_transfers_enabled(
            make_ctx(support_db), SetTransfersEnabledParams(enabled=True)
        )
    )
    assert result["before"] == {"transfers_enabled": 0, "block_reason": "compliance_review"}
    assert result["after"] == {"transfers_enabled": 1, "block_reason": None}


async def test_set_transfers_enabled_block_requires_reason(support_db):
    result = await _set_transfers_enabled(
        make_ctx(support_db), SetTransfersEnabledParams(enabled=False)
    )
    assert "requires a reason" in result


async def test_set_product_enabled_toggles_whitelisted_column(support_db):
    result = json.loads(
        await _set_product_enabled(
            make_ctx(support_db), SetProductEnabledParams(product="emprestimo", enabled=True)
        )
    )
    assert result["before"] == {"emprestimo": 0}
    assert result["after"] == {"emprestimo": 1}
