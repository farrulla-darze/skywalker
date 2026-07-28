"""Evaluation ORM models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

from .enums import Difficulty, EvalRunStatus, GoldenCategory, Provenance


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class GoldenItem(Base):
    __tablename__ = "golden_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="pt-BR")
    category: Mapped[str] = mapped_column(
        String(30), default=GoldenCategory.PRODUCT_HOWTO, nullable=False
    )
    difficulty: Mapped[str] = mapped_column(String(10), default=Difficulty.MEDIUM)
    expected_answer: Mapped[str] = mapped_column(Text, default="")
    expected_facts: Mapped[list] = mapped_column(JSON, default=list)
    gold_source_urls: Mapped[list] = mapped_column(JSON, default=list)
    expected_route: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_tools: Mapped[list] = mapped_column(JSON, default=list)
    provenance: Mapped[str] = mapped_column(
        String(30), default=Provenance.HANDCRAFTED, nullable=False
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    layer: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=EvalRunStatus.PENDING)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # frozen run configuration
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # aggregated results
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    item_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    retrieved_urls: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
