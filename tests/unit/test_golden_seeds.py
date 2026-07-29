"""Tests: golden dataset seed migration (legacy generations → getnet-v2)."""

import pytest

from app.core.db import Database
from app.modules.evaluation.models import GoldenItem
from app.modules.evaluation.repository import EvaluationRepository
from app.modules.evaluation.seeds import (
    ADVERSARIAL_ITEMS,
    QA_ITEMS,
    SEED_TAG,
    SUPPORT_ITEMS,
    seed_golden_items,
)

pytestmark = pytest.mark.anyio

EXPECTED_TOTAL = len(QA_ITEMS) + len(SUPPORT_ITEMS) + len(ADVERSARIAL_ITEMS)


@pytest.fixture
async def db():
    database = Database("sqlite+aiosqlite://")
    await database.create_all()
    yield database
    await database.dispose()


async def test_seed_inserts_getnet_v2_generation(db):
    async with db.session_factory() as session:
        await seed_golden_items(session)
        items = await EvaluationRepository(session).list_items()

    questions = [i.question for i in items]
    assert "What's the difference between the Get Clássica and the Get Smart?" in questions
    assert "How many installments can I split a sale into with the crediário?" in questions
    assert "What's the euro exchange rate today?" in questions
    assert len([i for i in items if i.reviewed_by == SEED_TAG]) == EXPECTED_TOTAL


async def test_qa_items_are_complete_golden_pairs(db):
    """Every Q&A item must ship a curated answer + curation metadata."""
    async with db.session_factory() as session:
        await seed_golden_items(session)
        items = await EvaluationRepository(session).list_items()

    qa = [
        i
        for i in items
        if i.reviewed_by == SEED_TAG
        and i.category in ("fees", "product_howto", "general_web")
    ]
    assert len(qa) >= 30, "the Langfuse golden dataset needs at least 30 active Q&A pairs"
    for item in qa:
        assert item.question.strip()
        assert item.expected_answer.strip(), f"missing expected_answer: {item.question!r}"
        assert item.expected_tools, f"missing expected_tools: {item.question!r}"
        assert item.meta.get("question_type"), f"missing meta.question_type: {item.question!r}"
        assert item.meta.get("answer_style"), f"missing meta.answer_style: {item.question!r}"


async def test_seed_archives_legacy_generations_and_is_idempotent(db):
    async with db.session_factory() as session:
        repository = EvaluationRepository(session)
        # Simulate the old InfinitePay and getnet-v1 seed generations
        await repository.create_item(
            GoldenItem(question="What are the fees of the Maquininha Smart", reviewed_by="seed")
        )
        await repository.create_item(
            GoldenItem(
                question="Can I sell through WhatsApp using the Payment Link?",
                reviewed_by="seed:getnet-v1",
            )
        )
        await seed_golden_items(session)
        await seed_golden_items(session)  # idempotent — no duplicates

        active = await repository.list_items()
        everything = await repository.list_items(include_archived=True)

    active_questions = [i.question for i in active]
    assert "What are the fees of the Maquininha Smart" not in active_questions
    assert "Can I sell through WhatsApp using the Payment Link?" not in active_questions
    legacy = [i for i in everything if i.reviewed_by in ("seed", "seed:getnet-v1")]
    assert legacy and all(i.archived for i in legacy)
    assert len([i for i in active if i.reviewed_by == SEED_TAG]) == EXPECTED_TOTAL
