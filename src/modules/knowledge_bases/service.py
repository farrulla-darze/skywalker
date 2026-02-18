"""Knowledge base service - business logic for ingestion and querying."""

import uuid
import logging
from pathlib import Path
from typing import Dict, Optional

from .schemas import (
    IngestStatus,
    KnowledgeBaseIngestCreate,
    KnowledgeBaseIngestResponse,
    KnowledgeBaseStatusRead,
    KnowledgeBaseQueryCreate,
    KnowledgeBaseQueryResponse,
    KnowledgeBaseSearchResultRead,
    UrlStatusRead,
)
from .scraper import WebScraper
from .chunker import MarkdownChunker
from .vector_store import PineconeVectorStore

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Orchestrates knowledge base ingestion and querying."""

    def __init__(
        self,
        vector_store: PineconeVectorStore,
        scraper: WebScraper,
        chunker: MarkdownChunker,
        md_output_dir: Path,
    ) -> None:
        self.vector_store = vector_store
        self.scraper = scraper
        self.chunker = chunker
        self.md_output_dir = md_output_dir
        self.md_output_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, KnowledgeBaseStatusRead] = {}

    def ingest_urls(self, request: KnowledgeBaseIngestCreate) -> KnowledgeBaseIngestResponse:
        """Create an ingestion job. Returns immediately; processing happens in background.

        Args:
            request: Ingestion request with URLs.

        Returns:
            Response with job_id for status tracking.
        """
        job_id = f"kb-{uuid.uuid4().hex[:12]}"

        url_statuses = [
            UrlStatusRead(url=str(url), status=IngestStatus.PENDING)
            for url in request.urls
        ]

        self._jobs[job_id] = KnowledgeBaseStatusRead(
            job_id=job_id,
            status=IngestStatus.PENDING,
            urls=url_statuses,
        )

        return KnowledgeBaseIngestResponse(
            job_id=job_id,
            status=IngestStatus.PENDING,
            urls_count=len(request.urls),
            message=f"Ingestion job created. Processing {len(request.urls)} URL(s) in the background.",
        )

    def get_job_status(self, job_id: str) -> Optional[KnowledgeBaseStatusRead]:
        """Get the current status of an ingestion job."""
        return self._jobs.get(job_id)

    async def run_ingestion_pipeline(
        self, job_id: str, request: KnowledgeBaseIngestCreate
    ) -> None:
        """Run the full ingestion pipeline for a job. Called as a background task.

        For each URL: scrape -> chunk -> embed -> upsert.
        Each URL is processed independently; failures don't block others.
        """
        job = self._jobs.get(job_id)
        if not job:
            return

        extra_metadata = request.metadata or {}
        total_chunks = 0
        total_vectors = 0
        any_success = False

        for i, url_str in enumerate([str(u) for u in request.urls]):
            url_status = job.urls[i]

            try:
                # 1. Scrape
                url_status.status = IngestStatus.SCRAPING
                scrape_result = await self.scraper.scrape_url(url_str)

                if not scrape_result.success:
                    url_status.status = IngestStatus.FAILED
                    url_status.error = scrape_result.error
                    logger.warning("Scrape failed for %s: %s", url_str, scrape_result.error)
                    continue

                # 2. Chunk
                url_status.status = IngestStatus.CHUNKING
                chunks = self.chunker.chunk_file(
                    file_path=str(scrape_result.file_path),
                    source_url=url_str,
                    content=scrape_result.markdown_content,
                )

                if not chunks:
                    url_status.status = IngestStatus.COMPLETED
                    url_status.chunks_count = 0
                    any_success = True
                    continue

                # 3. Embed and upsert
                url_status.status = IngestStatus.EMBEDDING
                vectors_count = await self.vector_store.upsert_chunks(
                    chunks=chunks,
                    namespace=request.namespace,
                    job_id=job_id,
                    extra_metadata=extra_metadata,
                )

                url_status.status = IngestStatus.COMPLETED
                url_status.chunks_count = len(chunks)
                total_chunks += len(chunks)
                total_vectors += vectors_count
                any_success = True

                logger.info(
                    "Ingested %s: %d chunks, %d vectors",
                    url_str, len(chunks), vectors_count,
                )

            except Exception as e:
                url_status.status = IngestStatus.FAILED
                url_status.error = str(e)
                logger.error("Pipeline failed for %s: %s", url_str, e, exc_info=True)

        job.total_chunks = total_chunks
        job.total_vectors_upserted = total_vectors
        job.status = IngestStatus.COMPLETED if any_success else IngestStatus.FAILED

        if not any_success:
            job.error = "All URLs failed to process"

    async def query(self, request: KnowledgeBaseQueryCreate) -> KnowledgeBaseQueryResponse:
        """Query the knowledge base with semantic search.

        Args:
            request: Query request.

        Returns:
            Ranked search results.
        """
        raw_results = await self.vector_store.query(
            query_text=request.query,
            top_k=request.top_k,
            namespace=request.namespace,
            filter=request.filter,
        )

        results = []
        for r in raw_results:
            meta = r.get("metadata", {})
            results.append(
                KnowledgeBaseSearchResultRead(
                    chunk_text=meta.get("chunk_text", ""),
                    score=r.get("score", 0.0),
                    source_url=meta.get("source_url", ""),
                    source_file=meta.get("source_file", ""),
                    chunk_index=meta.get("chunk_index", 0),
                    metadata={
                        k: v
                        for k, v in meta.items()
                        if k not in ("chunk_text", "source_url", "source_file", "chunk_index")
                    },
                )
            )

        return KnowledgeBaseQueryResponse(
            query=request.query,
            results=results,
            namespace=request.namespace,
        )
