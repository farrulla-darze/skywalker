"""Evaluation Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    Difficulty,
    EvalLayer,
    EvalRunStatus,
    ExpectedRoute,
    GoldenCategory,
    Provenance,
)


class GoldenItemCreate(BaseModel):
    question: str = Field(min_length=1)
    locale: str = "pt-BR"
    category: GoldenCategory = GoldenCategory.PRODUCT_HOWTO
    difficulty: Difficulty = Difficulty.MEDIUM
    expected_answer: str = ""
    expected_facts: list[str] = Field(default_factory=list)
    gold_source_urls: list[str] = Field(default_factory=list)
    expected_route: ExpectedRoute | None = None
    expected_tools: list[str] = Field(default_factory=list)
    provenance: Provenance = Provenance.HANDCRAFTED
    reviewed_by: str | None = None


class GoldenItemUpdate(BaseModel):
    question: str | None = None
    expected_answer: str | None = None
    expected_facts: list[str] | None = None
    gold_source_urls: list[str] | None = None
    expected_route: ExpectedRoute | None = None
    expected_tools: list[str] | None = None
    category: GoldenCategory | None = None
    difficulty: Difficulty | None = None
    archived: bool | None = None
    reviewed_by: str | None = None


class GoldenItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    locale: str
    category: GoldenCategory
    difficulty: Difficulty
    expected_answer: str
    expected_facts: list[str]
    gold_source_urls: list[str]
    expected_route: ExpectedRoute | None
    expected_tools: list[str]
    provenance: Provenance
    reviewed_by: str | None
    source_message_id: str | None
    archived: bool
    created_at: datetime


class EvalRunCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    layer: EvalLayer = EvalLayer.RETRIEVAL
    top_k: int = Field(default=5, ge=1, le=20)
    namespace: str | None = None


class EvalRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    layer: EvalLayer
    status: EvalRunStatus
    config: dict
    metrics: dict
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class EvalResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    item_id: str
    metrics: dict
    retrieved_urls: list[str]
    answer: str | None
    score: float | None


class PromoteFromMessageCreate(BaseModel):
    """Promote a chat answer (usually a thumbs-down) into a golden item draft."""

    message_id: str
    category: GoldenCategory = GoldenCategory.PRODUCT_HOWTO
    expected_answer: str = ""
    gold_source_urls: list[str] = Field(default_factory=list)
