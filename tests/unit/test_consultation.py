"""Tests: human-in-the-loop consultation — persistence, wait/answer handshake,
and the consult_human tool contract."""

import asyncio

import pytest

from app.core.config import Settings
from app.core.db import Database
from app.modules.integrations.models import HumanConsultation
from app.modules.integrations.repository import IntegrationsRepository
from app.modules.integrations.service import TelegramService
from app.modules.tools.definitions.escalation import CONSULT_SPEC, ConsultHumanParams
from app.modules.tools.service import ToolRunContext

pytestmark = pytest.mark.anyio

SETTINGS = Settings(langfuse_enabled=False, consultation_timeout_seconds=5)


@pytest.fixture
async def db():
    database = Database("sqlite+aiosqlite://")
    await database.create_all()
    yield database
    await database.dispose()


async def test_wait_resolves_when_human_answers_from_another_session(db):
    async with db.session_factory() as session:
        repository = IntegrationsRepository(session)
        consultation = await repository.save_consultation(
            HumanConsultation(session_id="s1", question="Posso aplicar o desconto?", context="ctx")
        )
        consultation_id = consultation.id
        service = TelegramService(repository, SETTINGS)

    async def human_answers_later():
        await asyncio.sleep(0.5)
        async with db.session_factory() as other_session:
            other_repo = IntegrationsRepository(other_session)
            row = await other_repo.get_consultation(consultation_id)
            row.answer = "Sim, aprovado até 10%."
            row.answered_by = "maria"
            row.status = "answered"
            await other_repo.save_consultation(row)

    service.CONSULTATION_POLL_SECONDS = 0.1
    answer_task = asyncio.create_task(human_answers_later())
    answered = await service.wait_for_consultation_answer(
        consultation_id, db.session_factory, timeout_seconds=5
    )
    await answer_task

    assert answered is not None
    assert answered.answer == "Sim, aprovado até 10%."
    assert answered.answered_by == "maria"


async def test_wait_times_out_when_no_answer(db):
    async with db.session_factory() as session:
        repository = IntegrationsRepository(session)
        consultation = await repository.save_consultation(
            HumanConsultation(session_id="s1", question="q", context="c")
        )
        service = TelegramService(repository, SETTINGS)

    service.CONSULTATION_POLL_SECONDS = 0.1
    answered = await service.wait_for_consultation_answer(
        consultation.id, db.session_factory, timeout_seconds=0.5
    )
    assert answered is None


async def test_consult_tool_returns_human_answer_via_ctx_callback():
    calls: list[tuple[str, str]] = []

    async def fake_consult(question: str, context: str) -> str:
        calls.append((question, context))
        return "Human specialist replied: aprovado."

    ctx = ToolRunContext(
        settings=SETTINGS, user_ref="u1", session_id="s1", consult=fake_consult
    )
    result = await CONSULT_SPEC.handler(
        ctx, ConsultHumanParams(question="Posso trocar o tier?", context="cliente Pro, R$80k/mês")
    )
    assert result == "Human specialist replied: aprovado."
    assert calls == [("Posso trocar o tier?", "cliente Pro, R$80k/mês")]


async def test_consult_tool_degrades_without_channel():
    ctx = ToolRunContext(settings=SETTINGS, user_ref="u1", session_id="s1", consult=None)
    result = await CONSULT_SPEC.handler(ctx, ConsultHumanParams(question="q", context="c"))
    assert "not configured" in result
    assert "not invent" in result or "Do not invent" in result
