"""Integrations persistence layer."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import TicketStatus
from .models import EscalationTicket, HumanConsultation, TelegramIntegration, TelegramLink


class IntegrationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Telegram integration --------------------------------------------

    async def get_integration(self, integration_id: str) -> TelegramIntegration | None:
        return await self.session.get(TelegramIntegration, integration_id)

    async def get_integration_for_owner(self, owner_id: str) -> TelegramIntegration | None:
        result = await self.session.execute(
            select(TelegramIntegration).where(TelegramIntegration.owner_id == owner_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def save_integration(self, integration: TelegramIntegration) -> TelegramIntegration:
        self.session.add(integration)
        await self.session.commit()
        await self.session.refresh(integration)
        return integration

    async def delete_integration(self, integration: TelegramIntegration) -> None:
        await self.session.delete(integration)
        await self.session.commit()

    # --- Links ------------------------------------------------------------

    async def get_link_by_code(self, code: str) -> TelegramLink | None:
        result = await self.session.execute(
            select(TelegramLink).where(TelegramLink.code == code)
        )
        return result.scalar_one_or_none()

    async def get_link_by_chat(self, integration_id: str, chat_id: int) -> TelegramLink | None:
        result = await self.session.execute(
            select(TelegramLink).where(
                TelegramLink.integration_id == integration_id,
                TelegramLink.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_link_for_user(self, integration_id: str, user_id: str) -> TelegramLink | None:
        result = await self.session.execute(
            select(TelegramLink).where(
                TelegramLink.integration_id == integration_id,
                TelegramLink.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def save_link(self, link: TelegramLink) -> TelegramLink:
        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)
        return link

    # --- Tickets ----------------------------------------------------------

    async def save_ticket(self, ticket: EscalationTicket) -> EscalationTicket:
        self.session.add(ticket)
        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def get_ticket(self, ticket_id: str) -> EscalationTicket | None:
        return await self.session.get(EscalationTicket, ticket_id)

    async def get_open_ticket_for_session(self, session_id: str) -> EscalationTicket | None:
        result = await self.session.execute(
            select(EscalationTicket)
            .where(
                EscalationTicket.session_id == session_id,
                EscalationTicket.status != TicketStatus.RESOLVED,
            )
            .order_by(EscalationTicket.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_tickets(self, limit: int = 100) -> list[EscalationTicket]:
        result = await self.session.execute(
            select(EscalationTicket).order_by(EscalationTicket.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def resolve_ticket(self, ticket: EscalationTicket) -> EscalationTicket:
        ticket.status = TicketStatus.RESOLVED
        ticket.resolved_at = datetime.now(UTC)
        return await self.save_ticket(ticket)

    # --- Human consultations ---------------------------------------------

    async def save_consultation(self, consultation: HumanConsultation) -> HumanConsultation:
        self.session.add(consultation)
        await self.session.commit()
        await self.session.refresh(consultation)
        return consultation

    async def get_consultation(self, consultation_id: str) -> HumanConsultation | None:
        return await self.session.get(HumanConsultation, consultation_id)

    async def find_open_consultation_by_message(
        self, telegram_message_id: int
    ) -> HumanConsultation | None:
        result = await self.session.execute(
            select(HumanConsultation).where(
                HumanConsultation.telegram_message_id == telegram_message_id,
                HumanConsultation.status == "open",
            )
        )
        return result.scalar_one_or_none()

    async def list_integrations_by_status(self, status: str) -> list[TelegramIntegration]:
        result = await self.session.execute(
            select(TelegramIntegration).where(TelegramIntegration.status == status)
        )
        return list(result.scalars().all())
