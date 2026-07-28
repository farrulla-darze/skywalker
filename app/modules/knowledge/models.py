"""Knowledge ORM models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

from .enums import IngestStatus


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class IngestionJob(Base):
    """Persisted ingestion job — survives restarts and works with multiple workers."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(20), default=IngestStatus.PENDING, nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    urls: Mapped[list] = mapped_column(JSON, default=list)
    # MutableList wraps the JSON list so in-place index assignment
    # (statuses[i] = {...}) is tracked by the ORM's dirty-checking —
    # a plain JSON column only detects whole-attribute reassignment to a
    # *different* object, and the ingestion pipeline mutates the same list
    # across iterations (see service.py run_ingestion_pipeline).
    url_statuses: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    total_vectors: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
