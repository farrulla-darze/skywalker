"""Integrations business logic.

Telegram plays two roles:
1. **Chat front-end** — an evaluator pairs their real Telegram account via a
   /start deep-link (rendered as QR in the frontend) and talks to the agent.
2. **Escalation channel** — the `escalate_to_human` tool posts a ticket with
   inline buttons to the configured support chat; claiming moves the session's
   handoff FSM to HUMAN and the LLM steps out until the ticket is resolved.

Handoff FSM:  bot → pending_human → human → bot
"""

import asyncio
import logging
import secrets
import uuid
from datetime import UTC

from app.core.config import Settings
from app.modules.chat.enums import ChatChannel, HandoffState, MessageRole
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.chat.repository import ChatRepository

from .enums import IntegrationStatus, IntegrationType, TicketStatus
from .models import EscalationTicket, HumanConsultation, TelegramIntegration, TelegramLink
from .repository import IntegrationsRepository
from .schemas import (
    IntegrationCatalogItemRead,
    TelegramIntegrationRead,
    TelegramLinkRead,
)
from .telegram_client import TelegramClient, TelegramClientError

logger = logging.getLogger(__name__)

CATALOG = [
    IntegrationCatalogItemRead(
        type=IntegrationType.TELEGRAM,
        name="Telegram",
        description="Use um bot do Telegram como front-end do agente e canal de escalação "
        "humana. Grátis: crie o bot no @BotFather e cole o token.",
        available=True,
    ),
    IntegrationCatalogItemRead(
        type=IntegrationType.SLACK,
        name="Slack",
        description="Mesmo contrato de canal de escalação, cliente Slack. Requer workspace "
        "corporativo — não incluído nesta demo.",
        available=False,
    ),
]


class IntegrationsError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramService:
    def __init__(self, repository: IntegrationsRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    # ------------------------------------------------------------------
    # Setup / pairing
    # ------------------------------------------------------------------

    async def connect(self, owner_id: str, bot_token: str) -> TelegramIntegrationRead:
        client = TelegramClient(bot_token)
        try:
            me = await client.get_me()
        except TelegramClientError as exc:
            raise IntegrationsError(f"Invalid bot token: {exc}", 400) from exc

        integration = await self.repository.get_integration_for_owner(owner_id)
        if integration is None:
            integration = TelegramIntegration(
                owner_id=owner_id,
                bot_token=bot_token,
                webhook_secret=secrets.token_urlsafe(32),
            )
        else:
            integration.bot_token = bot_token

        integration.bot_username = me.get("username", "")
        # Persist first — the id is needed to build the webhook URL
        integration = await self.repository.save_integration(integration)

        # Delivery mode: Telegram only accepts public HTTPS webhooks. For local
        # development (localhost / plain http) we fall back to long-polling —
        # no tunnel needed, and pending updates are drained on start.
        base = self.settings.public_base_url.lower()
        webhook_capable = base.startswith("https://") and "localhost" not in base and "127.0.0.1" not in base
        if webhook_capable:
            webhook_url = (
                f"{self.settings.public_base_url}/api/v1/integrations/telegram/webhook/"
                f"{integration.id}"
            )
            try:
                await client.set_webhook(webhook_url, integration.webhook_secret)
                integration.delivery = "webhook"
                integration.status = IntegrationStatus.CONNECTED
            except TelegramClientError as exc:
                logger.error("setWebhook failed, falling back to polling: %s", exc)
                webhook_capable = False
        if not webhook_capable:
            try:
                await client.delete_webhook()
            except TelegramClientError:
                pass
            integration.delivery = "polling"
            integration.status = IntegrationStatus.CONNECTED
        integration = await self.repository.save_integration(integration)
        return TelegramIntegrationRead.model_validate(integration)

    async def disconnect(self, owner_id: str) -> None:
        integration = await self.repository.get_integration_for_owner(owner_id)
        if integration is None:
            raise IntegrationsError("No Telegram integration configured", 404)
        try:
            await TelegramClient(integration.bot_token).delete_webhook()
        except TelegramClientError:
            pass
        await self.repository.delete_integration(integration)

    async def get_status(self, owner_id: str) -> TelegramIntegrationRead | None:
        integration = await self.repository.get_integration_for_owner(owner_id)
        return TelegramIntegrationRead.model_validate(integration) if integration else None

    async def get_pairing_link(self, owner_id: str) -> TelegramLinkRead:
        """Deep-link the frontend renders as a QR code for phone pairing."""
        integration = await self.repository.get_integration_for_owner(owner_id)
        if integration is None:
            raise IntegrationsError("Connect a Telegram bot first", 400)

        link = await self.repository.get_link_for_user(integration.id, owner_id)
        if link is None:
            link = TelegramLink(
                integration_id=integration.id,
                user_id=owner_id,
                code=uuid.uuid4().hex[:16],
            )
            link = await self.repository.save_link(link)

        return TelegramLinkRead(
            code=link.code,
            deep_link_url=f"https://t.me/{integration.bot_username}?start={link.code}",
            linked=link.chat_id is not None,
        )

    # ------------------------------------------------------------------
    # Escalation channel
    # ------------------------------------------------------------------

    async def create_escalation(
        self, session: ChatSession, reason: str, summary: str
    ) -> str:
        """Create a ticket and notify the support chat. Returns confirmation text."""
        integration = None
        if session.user_id:
            integration = await self.repository.get_integration_for_owner(session.user_id)

        ticket = EscalationTicket(
            session_id=session.id,
            integration_id=integration.id if integration else None,
            reason=reason,
            summary=summary,
        )
        ticket = await self.repository.save_ticket(ticket)

        if integration and integration.support_chat_id:
            client = TelegramClient(integration.bot_token)
            text = (
                f"🚨 Escalação · ticket {ticket.id[:8]}\n"
                f"Sessão: {session.id[:8]} · Cliente: {session.user_id or session.external_ref}\n"
                f"Motivo: {reason}\n\nResumo:\n{summary}"
            )
            markup = {
                "inline_keyboard": [[
                    {"text": "✋ Assumir", "callback_data": f"esc:{ticket.id}:claim"},
                    {"text": "✅ Resolver", "callback_data": f"esc:{ticket.id}:resolve"},
                ]]
            }
            try:
                message = await client.send_message(
                    integration.support_chat_id, text, reply_markup=markup
                )
                ticket.telegram_message_id = message.get("message_id")
                await self.repository.save_ticket(ticket)
            except TelegramClientError as exc:
                logger.error("Failed to notify support chat: %s", exc)
                return (
                    f"Ticket {ticket.id[:8]} created, but Telegram notification failed. "
                    "A human will review the queue."
                )
            return f"Ticket {ticket.id[:8]} created and the human support team was notified."

        return (
            f"Ticket {ticket.id[:8]} created. No Telegram support chat is configured, "
            "so the ticket waits in the queue."
        )

    async def forward_to_human(self, session: ChatSession, content: str) -> None:
        """While handoff_state != BOT, forward customer messages to the support chat."""
        ticket = await self.repository.get_open_ticket_for_session(session.id)
        if ticket is None or ticket.integration_id is None:
            return
        integration = await self.repository.get_integration(ticket.integration_id)
        if integration is None or integration.support_chat_id is None:
            return
        client = TelegramClient(integration.bot_token)
        await client.send_message(
            integration.support_chat_id,
            f"💬 Cliente ({session.user_id or session.external_ref}) "
            f"[ticket {ticket.id[:8]}]:\n{content}",
        )

    # ------------------------------------------------------------------
    # Human-in-the-loop consultation (agent stays in charge)
    # ------------------------------------------------------------------

    CONSULTATION_POLL_SECONDS = 2.0

    async def create_consultation(
        self,
        session: ChatSession,
        question: str,
        context: str,
        agent_label: str = "Agente",
        customer_display: str | None = None,
    ) -> HumanConsultation | None:
        """Post one precise agent→human question to the support chat.

        Returns None when no Telegram support chat is configured.
        """
        integration = None
        if session.user_id:
            integration = await self.repository.get_integration_for_owner(session.user_id)
        if integration is None or integration.support_chat_id is None:
            return None

        consultation = HumanConsultation(
            session_id=session.id,
            integration_id=integration.id,
            question=question,
            context=context,
        )
        consultation = await self.repository.save_consultation(consultation)

        customer = customer_display or session.user_id or session.external_ref or "anônimo"
        text = (
            f"🤝 Consulta · {agent_label} · {consultation.id[:8]}\n"
            f"Cliente: {customer}\n\n"
            f"Contexto:\n{context}\n\n"
            f"❓ Pergunta:\n{question}\n\n"
            f"↩️ Responda ESTA mensagem para enviar a resposta ao agente "
            f"(ele está aguardando). Se precisar de mais contexto, responda "
            f"perguntando — o agente fará um follow-up."
        )
        try:
            message = await TelegramClient(integration.bot_token).send_message(
                integration.support_chat_id, text
            )
            consultation.telegram_message_id = message.get("message_id")
            await self.repository.save_consultation(consultation)
        except TelegramClientError as exc:
            logger.error("Failed to post consultation to support chat: %s", exc)
            consultation.status = "failed"
            await self.repository.save_consultation(consultation)
            return None
        return consultation

    async def wait_for_consultation_answer(
        self, consultation_id: str, session_factory, timeout_seconds: float
    ) -> HumanConsultation | None:
        """Block until the human replies (webhook/polling writes the answer) or timeout.

        Polls the DB with fresh sessions — the answer is written by a different
        task (webhook request or polling loop), so the waiting turn must not
        reuse its own session's identity map.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self.CONSULTATION_POLL_SECONDS)
            async with session_factory() as fresh:
                consultation = await IntegrationsRepository(fresh).get_consultation(
                    consultation_id
                )
                if consultation and consultation.status == "answered":
                    return consultation
        return None

    # ------------------------------------------------------------------
    # Webhook processing
    # ------------------------------------------------------------------

    async def handle_update(
        self,
        integration: TelegramIntegration,
        update: dict,
        chat_repository: ChatRepository,
        run_agent_turn,
    ) -> None:
        """Process one Telegram update.

        ``run_agent_turn(session, text) -> str`` is injected by the API layer to
        avoid a circular dependency on ChatService.
        """
        if "callback_query" in update:
            await self._handle_callback(integration, update["callback_query"], chat_repository)
            return

        message = update.get("message")
        if not message or "text" not in message:
            return
        chat_id = message["chat"]["id"]
        text = message["text"].strip()

        # Pairing: /start <code>
        if text.startswith("/start"):
            await self._handle_start(integration, chat_id, text)
            return

        # Owner shortcut: register this chat as the support/escalation chat
        if text == "/support_here":
            integration.support_chat_id = chat_id
            await self.repository.save_integration(integration)
            await TelegramClient(integration.bot_token).send_message(
                chat_id, "✅ Este chat agora recebe as escalações humanas."
            )
            return

        link = await self.repository.get_link_by_chat(integration.id, chat_id)
        client = TelegramClient(integration.bot_token)

        # Support-chat replies to a ticket → forward to the customer's session
        if integration.support_chat_id == chat_id and message.get("reply_to_message"):
            await self._handle_support_reply(integration, message, chat_repository, client)
            return

        if link is None:
            await client.send_message(
                chat_id,
                "Este chat não está pareado. Abra o app Skywalker → Integrações → "
                "Telegram e escaneie o QR code para conectar.",
            )
            return

        # Paired customer message → find/create a telegram session and run the agent
        session = await chat_repository.find_session_by_external_ref(
            f"tg:{chat_id}", ChatChannel.TELEGRAM
        )
        if session is None:
            session = await chat_repository.create_session(
                ChatSession(
                    user_id=link.user_id,
                    external_ref=f"tg:{chat_id}",
                    channel=ChatChannel.TELEGRAM,
                    title="Telegram conversation",
                )
            )
        # Effective cap never undercuts a consult_human round (which can hold
        # the turn for consultation_timeout_seconds waiting on the human).
        turn_cap = max(
            self.settings.telegram_turn_timeout_seconds,
            self.settings.consultation_timeout_seconds + 120,
        )
        typing_task = asyncio.create_task(self._typing_loop(client, chat_id))
        try:
            reply_text = await asyncio.wait_for(run_agent_turn(session, text), timeout=turn_cap)
        except TimeoutError:
            logger.error(
                "Telegram turn exceeded %ss for session %s — sending fallback",
                turn_cap,
                session.id,
            )
            reply_text = (
                "Desculpe, estou demorando mais que o normal para responder. "
                "Pode tentar novamente em instantes?"
            )
        finally:
            typing_task.cancel()
        await client.send_message(chat_id, reply_text)

    @staticmethod
    async def _typing_loop(client: TelegramClient, chat_id: int) -> None:
        """Keep Telegram's 'typing…' indicator alive while the agent works."""
        while True:
            try:
                await client.send_chat_action(chat_id, "typing")
            except Exception:  # noqa: BLE001 — indicator is best-effort
                pass
            await asyncio.sleep(4.5)

    async def _handle_start(
        self, integration: TelegramIntegration, chat_id: int, text: str
    ) -> None:
        from datetime import datetime

        client = TelegramClient(integration.bot_token)
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        link = await self.repository.get_link_by_code(code) if code else None
        if link is None:
            await client.send_message(
                chat_id,
                "Olá! Para parear este chat, use o QR code na área de Integrações do app.",
            )
            return
        link.chat_id = chat_id
        link.linked_at = datetime.now(UTC)
        await self.repository.save_link(link)
        await client.send_message(
            chat_id,
            "✅ Pareado! Pode conversar comigo por aqui — sou o agente de suporte Getnet. "
            "Dica: envie /support_here para tornar este chat o canal de escalações humanas.",
        )

    async def _handle_support_reply(
        self,
        integration: TelegramIntegration,
        message: dict,
        chat_repository: ChatRepository,
        client: TelegramClient,
    ) -> None:
        replied_id = message["reply_to_message"].get("message_id")

        # Consultation replies take priority: the answer goes to the WAITING
        # AGENT (stored on the consultation row), never straight to the customer.
        consultation = await self.repository.find_open_consultation_by_message(replied_id)
        if consultation is not None:
            from datetime import UTC, datetime

            consultation.answer = message["text"]
            consultation.answered_by = message.get("from", {}).get("username") or str(
                message.get("from", {}).get("id", "?")
            )
            consultation.status = "answered"
            consultation.answered_at = datetime.now(UTC)
            await self.repository.save_consultation(consultation)
            if integration.support_chat_id is not None:
                await client.send_message(
                    integration.support_chat_id,
                    f"✔️ Resposta encaminhada ao agente (consulta {consultation.id[:8]}). "
                    f"Ele vai usá-la para responder o cliente — e pode fazer follow-up.",
                )
            return

        tickets = await self.repository.list_tickets()
        ticket = next((t for t in tickets if t.telegram_message_id == replied_id), None)
        if ticket is None:
            return
        session = await chat_repository.get_session(ticket.session_id)
        if session is None:
            return
        # Persist the human reply into the conversation
        await chat_repository.add_message(
            ChatMessage(
                session_id=session.id, role=MessageRole.HUMAN_AGENT, content=message["text"]
            )
        )
        # If the customer is on Telegram, push the reply there too
        if session.external_ref and session.external_ref.startswith("tg:"):
            customer_chat_id = int(session.external_ref.removeprefix("tg:"))
            await client.send_message(customer_chat_id, f"👤 Atendente: {message['text']}")

    async def _handle_callback(
        self, integration: TelegramIntegration, callback: dict, chat_repository: ChatRepository
    ) -> None:
        client = TelegramClient(integration.bot_token)
        data = callback.get("data", "")
        if not data.startswith("esc:"):
            return
        _, ticket_id, action = data.split(":", 2)
        ticket = await self.repository.get_ticket(ticket_id)
        if ticket is None:
            await client.answer_callback_query(callback["id"], "Ticket não encontrado")
            return

        session = await chat_repository.get_session(ticket.session_id)
        actor = callback.get("from", {}).get("username") or str(
            callback.get("from", {}).get("id", "?")
        )

        if action == "claim":
            ticket.status = TicketStatus.CLAIMED
            ticket.claimed_by = actor
            await self.repository.save_ticket(ticket)
            if session:
                session.handoff_state = HandoffState.HUMAN
                await chat_repository.save_session(session)
            await client.answer_callback_query(callback["id"], f"Assumido por @{actor}")
            await self._notify_customer(session, chat_repository, client,
                                        "👤 Um atendente humano assumiu sua conversa.")
        elif action == "resolve":
            await self.repository.resolve_ticket(ticket)
            if session:
                session.handoff_state = HandoffState.BOT
                await chat_repository.save_session(session)
            await client.answer_callback_query(callback["id"], "Resolvido — bot reassumiu")
            await self._notify_customer(session, chat_repository, client,
                                        "✅ Atendimento humano encerrado. O assistente voltou.")

    async def _notify_customer(
        self,
        session: ChatSession | None,
        chat_repository: ChatRepository,
        client: TelegramClient,
        text: str,
    ) -> None:
        if session is None:
            return
        await chat_repository.add_message(
            ChatMessage(session_id=session.id, role=MessageRole.SYSTEM, content=text)
        )
        if session.external_ref and session.external_ref.startswith("tg:"):
            await client.send_message(int(session.external_ref.removeprefix("tg:")), text)
