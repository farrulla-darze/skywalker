"""FastAPI routes for knowledge base management."""

from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException

from .schemas import (
    KnowledgeBaseIngestCreate,
    KnowledgeBaseIngestResponse,
    KnowledgeBaseStatusRead,
    KnowledgeBaseQueryCreate,
    KnowledgeBaseQueryResponse,
)
from .service import KnowledgeBaseService

kb_router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])

_kb_service: Optional[KnowledgeBaseService] = None


def set_kb_service(service: KnowledgeBaseService) -> None:
    """Set the global knowledge base service instance."""
    global _kb_service
    _kb_service = service


@kb_router.post("/ingest", response_model=KnowledgeBaseIngestResponse)
async def ingest_urls(
    request: KnowledgeBaseIngestCreate,
    background_tasks: BackgroundTasks,
) -> KnowledgeBaseIngestResponse:
    """Submit URLs for ingestion into the knowledge base.

    Returns immediately with a job_id. Processing runs in the background.
    Poll GET /knowledge-bases/jobs/{job_id} for status.
    """
    if not _kb_service:
        raise HTTPException(status_code=503, detail="Knowledge base service not initialized")

    response = _kb_service.ingest_urls(request)
    background_tasks.add_task(_kb_service.run_ingestion_pipeline, response.job_id, request)
    return response


@kb_router.get("/jobs/{job_id}", response_model=KnowledgeBaseStatusRead)
async def get_job_status(job_id: str) -> KnowledgeBaseStatusRead:
    """Get the status of an ingestion job."""
    if not _kb_service:
        raise HTTPException(status_code=503, detail="Knowledge base service not initialized")

    status = _kb_service.get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return status


@kb_router.post("/query", response_model=KnowledgeBaseQueryResponse)
async def query_knowledge_base(
    request: KnowledgeBaseQueryCreate,
) -> KnowledgeBaseQueryResponse:
    """Query the knowledge base with semantic search."""
    if not _kb_service:
        raise HTTPException(status_code=503, detail="Knowledge base service not initialized")

    return await _kb_service.query(request)
