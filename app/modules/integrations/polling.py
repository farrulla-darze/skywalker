"""Telegram long-polling delivery.

Telegram webhooks require a public HTTPS URL. In local development
(PUBLIC_BASE_URL = localhost) integrations connect in ``delivery="polling"``
mode instead: one background task per integration long-polls ``getUpdates``
and feeds each update through the same ``TelegramService.handle_update``
pipeline the webhook uses. Pending updates accumulated while the app was
down (or while the webhook was broken) are drained on start.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.core.config import Settings

from .repository import IntegrationsRepository
from .service import TelegramService
from .telegram_client import TelegramClient

if TYPE_CHECKING:
    from app.modules.chat.repository import ChatRepository

logger = logging.getLogger(__name__)

# Builds session -> (chat_repository, run_agent_turn) without a Request
UpdateContextBuilder = Callable[..., tuple["ChatRepository", Callable[..., Awaitable[str]]]]

IDLE_SLEEP_SECONDS = 1.0
ERROR_BACKOFF_SECONDS = 5.0


class TelegramPollingManager:
    """Owns one polling task per connected integration in polling mode."""

    def __init__(
        self,
        session_factory,
        settings: Settings,
        update_context_builder: UpdateContextBuilder,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.update_context_builder = update_context_builder
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_all(self) -> None:
        """Start polling for every connected polling-mode integration (app boot)."""
        async with self.session_factory() as session:
            integrations = await IntegrationsRepository(session).list_integrations_by_status(
                "connected"
            )
            polling_ids = [i.id for i in integrations if i.delivery == "polling"]
        for integration_id in polling_ids:
            self.start(integration_id)

    def start(self, integration_id: str) -> None:
        self.stop(integration_id)
        self._tasks[integration_id] = asyncio.create_task(
            self._poll_loop(integration_id), name=f"tg-poll-{integration_id[:8]}"
        )
        logger.info("Telegram polling started for integration %s", integration_id[:8])

    def stop(self, integration_id: str) -> None:
        task = self._tasks.pop(integration_id, None)
        if task and not task.done():
            task.cancel()

    async def stop_all(self) -> None:
        for integration_id in list(self._tasks):
            self.stop(integration_id)

    async def _poll_loop(self, integration_id: str) -> None:
        offset: int | None = None
        while True:
            try:
                async with self.session_factory() as session:
                    integration = await IntegrationsRepository(session).get_integration(
                        integration_id
                    )
                if (
                    integration is None
                    or integration.status != "connected"
                    or integration.delivery != "polling"
                ):
                    logger.info("Telegram polling stopping for %s", integration_id[:8])
                    return

                client = TelegramClient(integration.bot_token)
                updates = await client.get_updates(offset=offset, timeout=25)

                for update in updates:
                    offset = update["update_id"] + 1
                    await self._dispatch(integration_id, update)

                if not updates:
                    await asyncio.sleep(IDLE_SLEEP_SECONDS)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 — polling must survive anything
                logger.error("Telegram polling error (%s): %s", integration_id[:8], exc)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)

    async def _dispatch(self, integration_id: str, update: dict) -> None:
        """Process one update with fresh sessions, mirroring the webhook endpoint."""
        try:
            async with self.session_factory() as session:
                repository = IntegrationsRepository(session)
                integration = await repository.get_integration(integration_id)
                if integration is None:
                    return
                service = TelegramService(repository, self.settings)
                chat_repository, run_agent_turn = self.update_context_builder(session)
                await service.handle_update(
                    integration, update, chat_repository, run_agent_turn
                )
        except Exception as exc:  # noqa: BLE001 — one bad update must not kill the loop
            logger.error("Telegram update dispatch failed: %s", exc, exc_info=True)
