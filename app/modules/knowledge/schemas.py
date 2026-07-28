"""Knowledge Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .enums import IngestStatus


class KnowledgeIngestCreate(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=50)
    namespace: str | None = None


class KnowledgeIngestResponse(BaseModel):
    job_id: str
    status: IngestStatus
    urls_count: int
    message: str


class UrlStatusRead(BaseModel):
    url: str
    status: IngestStatus
    chunks_count: int = 0
    error: str | None = None


class KnowledgeJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: IngestStatus
    namespace: str
    urls: list[str]
    url_statuses: list[UrlStatusRead]
    total_chunks: int
    total_vectors: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeQueryCreate(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    namespace: str | None = None


class KnowledgeSearchResultRead(BaseModel):
    chunk_text: str
    score: float
    source_url: str
    header_context: str = ""


class KnowledgeQueryResponse(BaseModel):
    query: str
    namespace: str
    results: list[KnowledgeSearchResultRead]


class GraphProductRead(BaseModel):
    name: str
    slug: str
    url: str | None = None


class GraphExtractCreate(BaseModel):
    namespace: str | None = None


class GraphExtractResponse(BaseModel):
    namespace: str
    urls_processed: int
    urls_failed: int
    products_upserted: int
    fees_upserted: int
    features_upserted: int
    errors: list[str]
