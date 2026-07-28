"""Integrations Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import IntegrationStatus, IntegrationType, TicketStatus


class IntegrationCatalogItemRead(BaseModel):
    """Card in the frontend integrations library."""

    type: IntegrationType
    name: str
    description: str
    available: bool


class TelegramConnectCreate(BaseModel):
    bot_token: str = Field(min_length=20, description="Token from @BotFather")


class TelegramIntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bot_username: str
    status: IntegrationStatus
    delivery: str = "polling"  # "webhook" (public HTTPS) or "polling" (local dev)
    support_chat_id: int | None
    created_at: datetime


class TelegramLinkRead(BaseModel):
    """Deep-link for pairing — the frontend renders deep_link_url as a QR code."""

    code: str
    deep_link_url: str
    linked: bool


class EscalationTicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    reason: str
    summary: str
    status: TicketStatus
    claimed_by: str | None
    created_at: datetime
    resolved_at: datetime | None
