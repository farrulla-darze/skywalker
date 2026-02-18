"""
RAG search tool - Search the knowledge base vector database.

Uses Pinecone vector store to find relevant information from ingested documents.
"""

import logging
import os
import time
from threading import Event
from typing import Optional
from pydantic import BaseModel, Field

from .schema import ToolResult, TextContent, AgentTool
from ..knowledge_bases.vector_store import PineconeVectorStore

logger = logging.getLogger(__name__)

# Global vector store instance (initialized once)
_vector_store: Optional[PineconeVectorStore] = None
DEFAULT_PINECONE_NAMESPACE = "infinitepay"
RAG_SEARCH_TIMEOUT = 30.0  # seconds


def get_vector_store() -> PineconeVectorStore:
    """Get or create the global vector store instance."""
    global _vector_store

    if _vector_store is None:
        # Initialize from environment variables
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        pinecone_index_host = os.getenv("PINECONE_INDEX_HOST")
        openai_api_key = os.getenv("OPENAI_API_KEY")

        if not pinecone_api_key or not pinecone_index_host or not openai_api_key:
            raise ValueError(
                "Missing Pinecone/OpenAI credentials. "
                "Set PINECONE_API_KEY, PINECONE_INDEX_HOST, and OPENAI_API_KEY environment variables."
            )

        _vector_store = PineconeVectorStore(
            pinecone_api_key=pinecone_api_key,
            pinecone_index_host=pinecone_index_host,
            openai_api_key=openai_api_key,
        )

    return _vector_store


def get_default_namespace() -> str:
    """Get default Pinecone namespace from environment."""
    return os.getenv("PINECONE_NAMESPACE", DEFAULT_PINECONE_NAMESPACE)


class RagSearchParams(BaseModel):
    """Input parameters for the rag_search tool."""

    query: str = Field(
        ...,
        description="Natural language query to search in the knowledge base",
        examples=[
            "What are CloudWalk's payment gateway features?",
            "How do I integrate CloudWalk API?",
            "What is the refund policy?"
        ]
    )

    top_k: Optional[int] = Field(
        default=5,
        description="Number of most relevant results to return (default: 5)",
        ge=1,
        le=20
    )

    namespace: Optional[str] = Field(
        default=None,
        description=(
            "Pinecone namespace to search in. "
            "If omitted, uses PINECONE_NAMESPACE env var (or 'default')."
        )
    )

    class Config:
        extra = "forbid"
        use_enum_values = True


async def _execute_rag_search_tool(
    tool_call_id: str,
    params: RagSearchParams,
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the RAG search tool operation.

    Queries the Pinecone vector database for relevant documents.

    Args:
        tool_call_id: Unique identifier for this tool call
        params: Validated input parameters
        signal: Optional threading.Event for cancellation

    Returns:
        ToolResult with search results

    Raises:
        Exception: If search fails
    """
    start_time = time.time()

    if signal and signal.is_set():
        raise Exception("Operation aborted")

    try:
        vector_store = get_vector_store()
        resolved_namespace = params.namespace or get_default_namespace()
        query_preview = params.query[:80] + "..." if len(params.query) > 80 else params.query
        logger.info(f"[PERF] rag_search started: query='{query_preview}', top_k={params.top_k or 5}, namespace='{resolved_namespace}'")

        # Query the vector database with timeout
        import asyncio
        query_start = time.time()
        try:
            results = await asyncio.wait_for(
                vector_store.query(
                    query_text=params.query,
                    top_k=params.top_k or 5,
                    namespace=resolved_namespace,
                    filter=None,
                ),
                timeout=RAG_SEARCH_TIMEOUT
            )
            query_duration = time.time() - query_start
            logger.info(f"[PERF] Pinecone vector query completed: duration={query_duration:.2f}s, results={len(results)}")
        except asyncio.TimeoutError:
            total_duration = time.time() - start_time
            logger.warning(f"[PERF] rag_search timed out after {RAG_SEARCH_TIMEOUT}s: query='{query_preview}'")
            return ToolResult(
                content=[TextContent(text=f"RAG search timed out after {RAG_SEARCH_TIMEOUT} seconds. Please try again with a more specific query.")],
                details={"error": "timeout", "duration_seconds": round(total_duration, 2), "timeout_seconds": RAG_SEARCH_TIMEOUT}
            )

        if signal and signal.is_set():
            raise Exception("Operation aborted")

        if not results:
            output_text = f"No results found in knowledge base for: {params.query}"
        else:
            output_text = f"Knowledge base results for '{params.query}':\n\n"

            for i, result in enumerate(results, 1):
                metadata = result.get("metadata", {})
                score = result.get("score", 0.0)
                chunk_text = metadata.get("chunk_text", "")
                source_url = metadata.get("source_url", "")
                source_file = metadata.get("source_file", "")

                output_text += f"**Result {i}** (Relevance: {score:.2f})\n"

                if source_url:
                    output_text += f"Source: {source_url}\n"
                elif source_file:
                    output_text += f"Source: {source_file}\n"

                output_text += f"\n{chunk_text}\n"
                output_text += "\n" + "-" * 80 + "\n\n"

        total_duration = time.time() - start_time
        logger.info(f"[PERF] rag_search completed: total_duration={total_duration:.2f}s, results={len(results)}")

        return ToolResult(
            content=[TextContent(text=output_text)],
            details={
                "query": params.query,
                "results_count": len(results),
                "namespace": resolved_namespace,
                "duration_seconds": round(total_duration, 2)
            }
        )

    except Exception as e:
        total_duration = time.time() - start_time
        query_preview = params.query[:80] + "..." if len(params.query) > 80 else params.query
        logger.error(f"[PERF] rag_search failed: duration={total_duration:.2f}s, query='{query_preview}', error={e}")
        error_msg = f"Knowledge base search failed: {str(e)}"
        return ToolResult(
            content=[TextContent(text=error_msg)],
            details={"error": str(e), "duration_seconds": round(total_duration, 2)}
        )


def create_rag_search_tool() -> AgentTool:
    """
    Create a RAG search tool for querying the knowledge base.

    Returns:
        AgentTool descriptor for the RAG search tool
    """
    async def execute(
        tool_call_id: str,
        params: RagSearchParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the RAG search tool."""
        return await _execute_rag_search_tool(
            tool_call_id,
            params,
            signal,
        )

    return AgentTool(
        name="rag_search",
        label="rag_search",
        description=(
            "Search the CloudWalk knowledge base for product documentation, policies, "
            "and support articles. Use this tool when you need to find information about "
            "CloudWalk products, services, policies, or procedures that has been previously "
            "ingested into the system. Returns relevant document chunks with similarity scores."
        ),
        parameters_schema=RagSearchParams,
        execute=execute,
    )
