"""Chat ORM models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

from .enums import ChatChannel, HandoffState, MessageRole


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    # For anonymous/legacy/telegram traffic: an external user reference
    external_ref: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    channel: Mapped[str] = mapped_column(String(20), default=ChatChannel.WEB, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None = default router
    handoff_state: Mapped[str] = mapped_column(
        String(20), default=HandoffState.BOT, nullable=False
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default=MessageRole.USER, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)  # list[StepRecord]
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Langfuse trace id of the turn that produced this message — lets the
    # frontend attach scores/annotations to the exact trace.
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("chat_messages.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
