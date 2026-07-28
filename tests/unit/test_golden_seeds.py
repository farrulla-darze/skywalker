"""Tests: golden dataset seed migration (legacy generation → getnet-v1)."""

import pytest

from app.core.db import Database
from app.modules.evaluation.models import GoldenItem
from app.modules.evaluation.repository import EvaluationRepository
from app.modules.evaluation.seeds import SEED_TAG, seed_golden_items

pytestmark = pytest.mark.anyio


@pytest.fixture
async def db():
    database = Database("sqlite+aiosqlite://")
    await database.create_all()
    yield database
    await database.dispose()


async def test_seed_inserts_getnet_generation(db):
    async with db.session_factory() as session:
        await seed_golden_items(session)
        items = await EvaluationRepository(session).list_items()

    questions = [i.question for i in items]
    assert "What's the difference between the Get Clássica and the Get Smart?" in questions
    assert "How many installments can I split a sale into with the crediário?" in questions
    assert len([i for i in items if i.reviewed_by == SEED_TAG]) == 12  # 10 challenge + 2 adv


async def test_seed_archives_legacy_generation_and_is_idempotent(db):
    async with db.session_factory() as session:
        repository = EvaluationRepository(session)
        # Simulate the old InfinitePay seed generation
        await repository.create_item(
            GoldenItem(question="What are the fees of the Maquininha Smart", reviewed_by="seed")
        )
        await seed_golden_items(session)
        await seed_golden_items(session)  # idempotent — no duplicates

        active = await repository.list_items()
        everything = await repository.list_items(include_archived=True)

    active_questions = [i.question for i in active]
    assert "What are the fees of the Maquininha Smart" not in active_questions, (
        "legacy seed item should be archived"
    )
    legacy = [i for i in everything if i.reviewed_by == "seed"]
    assert legacy and all(i.archived for i in legacy)
    assert len([i for i in active if i.reviewed_by == SEED_TAG]) == 12
