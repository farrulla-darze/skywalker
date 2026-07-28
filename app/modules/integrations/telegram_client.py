"""Thin async client over the Telegram Bot API (no SDK dependency)."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramClientError(Exception):
    pass


class TelegramClient:
    def __init__(self, bot_token: str, timeout: float = 40.0) -> None:
        # 40s default accommodates getUpdates long-polling (25s server-side hold)
        self.bot_token = bot_token
        self.timeout = timeout

    async def _call(self, method: str, **params: Any) -> dict:
        url = f"{API_BASE}/bot{self.bot_token}/{method}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json={k: v for k, v in params.items() if v is not None})
        data = response.json()
        if not data.get("ok"):
            raise TelegramClientError(f"{method} failed: {data.get('description', response.text)}")
        return data["result"]

    async def get_me(self) -> dict:
        return await self._call("getMe")

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self._call(
            "setWebhook",
            url=url,
            secret_token=secret_token,
            allowed_updates=["message", "callback_query"],
        )

    async def delete_webhook(self) -> None:
        await self._call("deleteWebhook")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
    ) -> dict:
        return await self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text[:4096],
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        await self._call("answerCallbackQuery", callback_query_id=callback_query_id, text=text)

    async def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict]:
        """Long-poll for updates (polling delivery mode). Requires no webhook set."""
        result = await self._call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=["message", "callback_query"],
        )
        return result if isinstance(result, list) else []
