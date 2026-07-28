"""Chat module enums."""

from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    HUMAN_AGENT = "human_agent"
    SYSTEM = "system"


class ChatChannel(StrEnum):
    WEB = "web"
    TELEGRAM = "telegram"
    API = "api"  # legacy challenge endpoint


class HandoffState(StrEnum):
    BOT = "bot"
    PENDING_HUMAN = "pending_human"
    HUMAN = "human"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"
