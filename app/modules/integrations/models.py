"""Integrations ORM models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

from .enums import IntegrationStatus, TicketStatus


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class TelegramIntegration(Base):
    """A user-configured Telegram bot connection."""

    __tablename__ = "telegram_integrations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    bot_token: Mapped[str] = mapped_column(String(120), nullable=False)
    bot_username: Mapped[str] = mapped_column(String(120), default="")
    webhook_secret: Mapped[str] = mapped_column(String(64), nullable=False)
    # Chat where escalation tickets are posted (the owner's own chat by default)
    support_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=IntegrationStatus.DISCONNECTED, nullable=False
    )
    # How updates reach us: "webhook" (public HTTPS) or "polling" (local dev)
    delivery: Mapped[str] = mapped_column(String(16), default="polling", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HumanConsultation(Base):
    """One agent→human question round (human-in-the-loop consultation).

    Unlike an EscalationTicket (full conversation handoff), a consultation keeps
    the agent in charge: it asks the support staff a precise question on
    Telegram, blocks the turn until the reply (or timeout), and uses the answer
    to respond to the customer. Follow-ups are new consultation rows.
    """

    __tablename__ = "human_consultations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    integration_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramLink(Base):
    """Pairing between a platform user and a Telegram chat via /start deep-link code."""

    __tablename__ = "telegram_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    integration_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("telegram_integrations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EscalationTicket(Base):
    __tablename__ = "escalation_tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    integration_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=TicketStatus.OPEN, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
