"""Integrations HTTP layer, including the Telegram webhook."""

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.api.v1.dependencies import CurrentUserDep, SessionDep, SettingsDep
from app.modules.chat.repository import ChatRepository

from .repository import IntegrationsRepository
from .schemas import (
    EscalationTicketRead,
    IntegrationCatalogItemRead,
    TelegramConnectCreate,
    TelegramIntegrationRead,
    TelegramLinkRead,
)
from .service import CATALOG, IntegrationsError, TelegramService

logger = logging.getLogger(__name__)

integrations_router = APIRouter(prefix="/integrations", tags=["integrations"])


def _service(session, settings) -> TelegramService:
    return TelegramService(IntegrationsRepository(session), settings)


@integrations_router.get("/catalog", response_model=list[IntegrationCatalogItemRead])
async def catalog(_user: CurrentUserDep) -> list[IntegrationCatalogItemRead]:
    return CATALOG


@integrations_router.get("/telegram", response_model=TelegramIntegrationRead | None)
async def telegram_status(session: SessionDep, settings: SettingsDep, user: CurrentUserDep):
    return await _service(session, settings).get_status(user.id)


@integrations_router.post("/telegram/connect", response_model=TelegramIntegrationRead)
async def telegram_connect(
    payload: TelegramConnectCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    try:
        result = await _service(session, settings).connect(user.id, payload.bot_token)
    except IntegrationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    polling = getattr(request.app.state, "telegram_polling", None)
    if polling is not None:
        if result.delivery == "polling":
            polling.start(result.id)
        else:
            polling.stop(result.id)
    return result


@integrations_router.delete("/telegram", status_code=204)
async def telegram_disconnect(
    request: Request, session: SessionDep, settings: SettingsDep, user: CurrentUserDep
):
    service = _service(session, settings)
    existing = await service.get_status(user.id)
    try:
        await service.disconnect(user.id)
    except IntegrationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    polling = getattr(request.app.state, "telegram_polling", None)
    if polling is not None and existing is not None:
        polling.stop(existing.id)


@integrations_router.get("/telegram/pairing-link", response_model=TelegramLinkRead)
async def telegram_pairing_link(
    session: SessionDep, settings: SettingsDep, user: CurrentUserDep
):
    try:
        return await _service(session, settings).get_pairing_link(user.id)
    except IntegrationsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@integrations_router.get("/tickets", response_model=list[EscalationTicketRead])
async def list_tickets(session: SessionDep, _user: CurrentUserDep):
    tickets = await IntegrationsRepository(session).list_tickets()
    return [EscalationTicketRead.model_validate(t) for t in tickets]


# ---------------------------------------------------------------------------
# Telegram webhook (unauthenticated — validated by the per-bot secret token)
# ---------------------------------------------------------------------------


@integrations_router.post("/telegram/webhook/{integration_id}", include_in_schema=False)
async def telegram_webhook(
    integration_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    repository = IntegrationsRepository(session)
    integration = await repository.get_integration(integration_id)
    if integration is None:
        raise HTTPException(status_code=404)
    if x_telegram_bot_api_secret_token != integration.webhook_secret:
        raise HTTPException(status_code=403)

    update = await request.json()
    chat_repository = ChatRepository(session)

    async def run_agent_turn(chat_session, text: str) -> str:
        from app.modules.chat.api import build_chat_service

        service = build_chat_service(request, session, settings)
        message = await service.run_turn(chat_session, text)
        return message.content

    telegram_service = _service(session, settings)
    try:
        await telegram_service.handle_update(integration, update, chat_repository, run_agent_turn)
    except Exception as exc:  # noqa: BLE001 — always ACK Telegram to avoid redelivery storms
        logger.error("Telegram update failed: %s", exc, exc_info=True)
    return {"ok": True}
