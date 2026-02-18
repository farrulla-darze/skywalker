"""Pinecone vector store for knowledge base embeddings."""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pinecone import Pinecone
from openai import AsyncOpenAI

from .chunker import Chunk

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 1024
UPSERT_BATCH_SIZE = 100
EMBED_BATCH_SIZE = 100


class PineconeVectorStore:
    """Handles embedding generation and Pinecone vector operations."""

    def __init__(
        self,
        pinecone_api_key: str,
        pinecone_index_host: str,
        openai_api_key: str,
    ) -> None:
        self.pc = Pinecone(api_key=pinecone_api_key)
        self.index = self.pc.Index(host=pinecone_index_host)
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI text-embedding-3-large.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (1024-dimensional).
        """
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            response = await self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
                dimensions=EMBEDDING_DIMENSION,
            )
            all_embeddings.extend([item.embedding for item in response.data])

        return all_embeddings

    async def upsert_chunks(
        self,
        chunks: List[Chunk],
        namespace: str = "default",
        job_id: str = "",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Embed and upsert chunks into Pinecone.

        Args:
            chunks: List of Chunk objects to embed and store.
            namespace: Pinecone namespace.
            job_id: Ingestion job identifier.
            extra_metadata: Additional metadata to attach to each vector.

        Returns:
            Number of vectors upserted.
        """
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = await self.embed_texts(texts)
        now = datetime.now(timezone.utc).isoformat()

        vectors = []
        for chunk, embedding in zip(chunks, embeddings):
            metadata: Dict[str, Any] = {
                "chunk_text": chunk.text[:40000],  # Pinecone metadata size limit
                "source_url": chunk.source_url,
                "source_file": chunk.source_file,
                "chunk_index": chunk.chunk_index,
                "header_context": chunk.header_context,
                "ingested_at": now,
                "job_id": job_id,
                "char_count": len(chunk.text),
            }
            if extra_metadata:
                metadata.update(extra_metadata)

            vectors.append(
                {
                    "id": self._chunk_to_vector_id(chunk),
                    "values": embedding,
                    "metadata": metadata,
                }
            )

        # Batch upsert
        total_upserted = 0
        for i in range(0, len(vectors), UPSERT_BATCH_SIZE):
            batch = vectors[i : i + UPSERT_BATCH_SIZE]
            self.index.upsert(vectors=batch, namespace=namespace)
            total_upserted += len(batch)

        logger.info("Upserted %d vectors to namespace '%s'", total_upserted, namespace)
        return total_upserted

    async def query(
        self,
        query_text: str,
        top_k: int = 5,
        namespace: str = "default",
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Query Pinecone with a text query.

        Args:
            query_text: Natural language query.
            top_k: Number of results to return.
            namespace: Pinecone namespace to search.
            filter: Optional metadata filter.

        Returns:
            List of scored results with metadata.
        """
        embeddings = await self.embed_texts([query_text])
        query_vector = embeddings[0]

        results = self.index.query(
            vector=query_vector,
            top_k=top_k,
            namespace=namespace,
            filter=filter,
            include_metadata=True,
        )

        return [
            {
                "id": match["id"],
                "score": match["score"],
                "metadata": match.get("metadata", {}),
            }
            for match in results.get("matches", [])
        ]

    def _chunk_to_vector_id(self, chunk: Chunk) -> str:
        """Generate deterministic vector ID from chunk source and index."""
        raw = f"{chunk.source_url}::{chunk.chunk_index}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
