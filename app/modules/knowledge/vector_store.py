"""Qdrant vector store — embedding generation and vector CRUD.

One collection holds all namespaces; each point carries a ``namespace``
payload field used as a mandatory filter at query time.
"""

import hashlib
import logging
import uuid
from typing import Any

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import Settings

from .chunker import Chunk

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 100


class QdrantVectorStore:
    """Handles embeddings (OpenAI) and vector operations (Qdrant)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.collection = settings.qdrant_collection
        self.client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        self.openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist (idempotent)."""
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.settings.embedding_dimensions, distance=Distance.COSINE
                ),
            )
            logger.info("Created Qdrant collection '%s'", self.collection)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            response = await self.openai_client.embeddings.create(
                model=self.settings.embedding_model,
                input=batch,
                dimensions=self.settings.embedding_dimensions,
            )
            all_embeddings.extend(item.embedding for item in response.data)
        return all_embeddings

    async def upsert_chunks(
        self,
        chunks: list[Chunk],
        namespace: str,
        job_id: str = "",
        extra_metadata: dict[str, Any] | None = None,
    ) -> int:
        if not chunks:
            return 0
        await self.ensure_collection()
        embeddings = await self.embed_texts([c.text for c in chunks])

        points = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            payload: dict[str, Any] = {
                "namespace": namespace,
                "chunk_text": chunk.text,
                "body": chunk.body,
                "source_url": chunk.source_url,
                "chunk_index": chunk.chunk_index,
                "header_context": chunk.header_context,
                "job_id": job_id,
            }
            if extra_metadata:
                payload.update(extra_metadata)
            points.append(
                PointStruct(
                    id=self._chunk_point_id(namespace, chunk),
                    vector=embedding,
                    payload=payload,
                )
            )

        await self.client.upsert(collection_name=self.collection, points=points)
        logger.info("Upserted %d vectors into namespace '%s'", len(points), namespace)
        return len(points)

    async def query(
        self,
        query_text: str,
        top_k: int = 5,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search. Returns [{id, score, metadata}] ranked by similarity."""
        namespace = namespace or self.settings.default_namespace
        embeddings = await self.embed_texts([query_text])

        result = await self.client.query_points(
            collection_name=self.collection,
            query=embeddings[0],
            limit=top_k,
            query_filter=Filter(
                must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
            ),
            with_payload=True,
        )
        return [
            {"id": str(point.id), "score": point.score, "metadata": point.payload or {}}
            for point in result.points
        ]

    async def list_chunks(self, namespace: str) -> list[dict[str, Any]]:
        """Scroll ALL chunk payloads for a namespace (used by graph fact extraction)."""
        payloads: list[dict[str, Any]] = []
        offset = None
        while True:
            points, offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
                ),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            payloads.extend(point.payload or {} for point in points)
            if offset is None:
                break
        return payloads

    @staticmethod
    def _chunk_point_id(namespace: str, chunk: Chunk) -> str:
        """Deterministic UUID from namespace + source + index (re-ingestion overwrites)."""
        raw = f"{namespace}::{chunk.source_url}::{chunk.chunk_index}"
        return str(uuid.UUID(hashlib.sha256(raw.encode()).hexdigest()[:32]))
