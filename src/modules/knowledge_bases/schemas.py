"""Pydantic schemas for knowledge base operations."""

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


class IngestStatus(str, Enum):
    """Status of an ingestion job."""

    PENDING = "pending"
    SCRAPING = "scraping"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeBaseIngestCreate(BaseModel):
    """Request to ingest one or more URLs into the knowledge base."""

    urls: List[HttpUrl] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of URLs to scrape and ingest",
    )
    namespace: str = Field(
        default="default",
        description="Pinecone namespace to store vectors in",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to attach to all vectors from this batch",
    )


class UrlStatusRead(BaseModel):
    """Status for a single URL in an ingestion job."""

    url: str
    status: IngestStatus
    chunks_count: int = 0
    error: Optional[str] = None


class KnowledgeBaseIngestResponse(BaseModel):
    """Response after submitting an ingestion request."""

    job_id: str = Field(..., description="Unique identifier for tracking this ingestion job")
    status: IngestStatus = Field(default=IngestStatus.PENDING)
    urls_count: int
    message: str


class KnowledgeBaseStatusRead(BaseModel):
    """Status of a running or completed ingestion job."""

    job_id: str
    status: IngestStatus
    urls: List[UrlStatusRead]
    total_chunks: int = 0
    total_vectors_upserted: int = 0
    error: Optional[str] = None


class KnowledgeBaseQueryCreate(BaseModel):
    """Request to query the knowledge base."""

    query: str = Field(..., min_length=1, description="Natural language query")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of results")
    namespace: str = Field(default="default")
    filter: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pinecone metadata filter",
    )


class KnowledgeBaseSearchResultRead(BaseModel):
    """A single search result from the knowledge base."""

    chunk_text: str
    score: float
    source_url: str
    source_file: str
    chunk_index: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeBaseQueryResponse(BaseModel):
    """Response from a knowledge base query."""

    query: str
    results: List[KnowledgeBaseSearchResultRead]
    namespace: str
