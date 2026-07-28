"""rag_search — semantic search over the ingested knowledge base (Qdrant)."""

import asyncio
import logging

from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 30.0


class RagSearchParams(BaseModel):
    query: str = Field(description="Natural language query to search in the knowledge base")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of results to return")
    namespace: str | None = Field(
        default=None, description="Knowledge base namespace (defaults to the configured one)"
    )


async def _handler(ctx: ToolRunContext, params: RagSearchParams) -> str:
    if ctx.vector_store is None:
        return "Knowledge base is not configured."

    try:
        results = await asyncio.wait_for(
            ctx.vector_store.query(
                query_text=params.query,
                top_k=params.top_k,
                namespace=params.namespace or ctx.settings.default_namespace,
            ),
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return f"Knowledge base search timed out after {SEARCH_TIMEOUT_SECONDS:.0f}s."
    except Exception as exc:  # noqa: BLE001 — tool errors are surfaced to the LLM as text
        logger.error("rag_search failed: %s", exc, exc_info=True)
        return f"Knowledge base search failed: {exc}"

    if not results:
        return f"No results found in the knowledge base for: {params.query}"

    lines = [f"Knowledge base results for '{params.query}':\n"]
    for i, result in enumerate(results, 1):
        meta = result["metadata"]
        lines.append(f"**Result {i}** (score: {result['score']:.2f})")
        if meta.get("source_url"):
            lines.append(f"Source: {meta['source_url']}")
        lines.append(meta.get("chunk_text", ""))
        lines.append("-" * 60)
    return "\n".join(lines)


SPEC = ToolSpec(
    name="rag_search",
    label="Knowledge Base Search",
    description=(
        "Search the Getnet knowledge base for product documentation, fees, "
        "features and procedures. Returns relevant chunks with source URLs — "
        "always cite the source URL when using a result."
    ),
    category=ToolCategory.KNOWLEDGE,
    params_model=RagSearchParams,
    handler=_handler,
)
