"""Knowledge business logic — ingestion pipeline orchestration and querying."""

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings

from .chunker import MarkdownChunker
from .enums import IngestStatus
from .models import IngestionJob
from .repository import KnowledgeRepository
from .schemas import (
    KnowledgeIngestCreate,
    KnowledgeIngestResponse,
    KnowledgeQueryCreate,
    KnowledgeQueryResponse,
    KnowledgeSearchResultRead,
)
from .scraper import WebScraper
from .vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


class KnowledgeService:
    """Orchestrates scrape → chunk → embed → upsert and semantic querying."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        vector_store: QdrantVectorStore,
        settings: Settings,
        scraper: WebScraper | None = None,
        chunker: MarkdownChunker | None = None,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self.settings = settings
        self.scraper = scraper or WebScraper()
        self.chunker = chunker or MarkdownChunker()

    async def create_ingestion_job(self, request: KnowledgeIngestCreate) -> KnowledgeIngestResponse:
        namespace = request.namespace or self.settings.default_namespace
        urls = [str(u) for u in request.urls]
        job = IngestionJob(
            namespace=namespace,
            urls=urls,
            url_statuses=[
                {"url": u, "status": IngestStatus.PENDING, "chunks_count": 0, "error": None}
                for u in urls
            ],
        )
        job = await self.repository.create_job(job)
        return KnowledgeIngestResponse(
            job_id=job.id,
            status=IngestStatus.PENDING,
            urls_count=len(urls),
            message=f"Ingestion job created. Processing {len(urls)} URL(s) in the background.",
        )

    async def run_ingestion_pipeline(
        self, job_id: str, session_factory: async_sessionmaker
    ) -> None:
        """Background task. Opens its own DB session (request session is gone by now)."""
        async with session_factory() as session:
            repository = KnowledgeRepository(session)
            job = await repository.get_job(job_id)
            if job is None:
                return

            job.status = IngestStatus.SCRAPING
            await repository.save(job)

            statuses = list(job.url_statuses)
            total_chunks = 0
            total_vectors = 0
            any_success = False

            for i, url in enumerate(job.urls):
                try:
                    statuses[i] = {**statuses[i], "status": IngestStatus.SCRAPING}
                    scrape = await self.scraper.scrape_url(url)
                    if not scrape.success:
                        statuses[i] = {
                            **statuses[i], "status": IngestStatus.FAILED, "error": scrape.error,
                        }
                        continue

                    statuses[i] = {**statuses[i], "status": IngestStatus.CHUNKING}
                    chunks = self.chunker.chunk(scrape.markdown, source_url=url)

                    statuses[i] = {**statuses[i], "status": IngestStatus.EMBEDDING}
                    vectors = await self.vector_store.upsert_chunks(
                        chunks, namespace=job.namespace, job_id=job.id
                    )

                    statuses[i] = {
                        **statuses[i],
                        "status": IngestStatus.COMPLETED,
                        "chunks_count": len(chunks),
                    }
                    total_chunks += len(chunks)
                    total_vectors += vectors
                    any_success = True
                except Exception as exc:  # noqa: BLE001 — per-URL isolation is intentional
                    logger.error("Ingestion failed for %s: %s", url, exc, exc_info=True)
                    statuses[i] = {**statuses[i], "status": IngestStatus.FAILED, "error": str(exc)}

                # Persist progress after each URL so job polling reflects reality
                job.url_statuses = statuses
                job.total_chunks = total_chunks
                job.total_vectors = total_vectors
                await repository.save(job)

            job.status = IngestStatus.COMPLETED if any_success else IngestStatus.FAILED
            if not any_success:
                job.error = "All URLs failed to process"
            await repository.save(job)

    async def query(self, request: KnowledgeQueryCreate) -> KnowledgeQueryResponse:
        namespace = request.namespace or self.settings.default_namespace
        raw = await self.vector_store.query(
            query_text=request.query, top_k=request.top_k, namespace=namespace
        )
        results = [
            KnowledgeSearchResultRead(
                chunk_text=r["metadata"].get("chunk_text", ""),
                score=r["score"],
                source_url=r["metadata"].get("source_url", ""),
                header_context=r["metadata"].get("header_context", ""),
            )
            for r in raw
        ]
        return KnowledgeQueryResponse(query=request.query, namespace=namespace, results=results)
