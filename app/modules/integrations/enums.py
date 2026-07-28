"""Integrations enums."""

from enum import StrEnum


class IntegrationType(StrEnum):
    TELEGRAM = "telegram"
    SLACK = "slack"  # declared, not implemented — same EscalationChannel contract


class IntegrationStatus(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class TicketStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    RESOLVED = "resolved"
