"""web_search — real-time internet search via DuckDuckGo (ddgs)."""

import asyncio
import logging

from ddgs import DDGS
from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 2


class WebSearchParams(BaseModel):
    query: str = Field(description="Search query to look up on the internet")
    max_results: int = Field(default=5, ge=1, le=10)


def _search_sync(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def _handler(ctx: ToolRunContext, params: WebSearchParams) -> str:
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(_search_sync, params.query, params.max_results),
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("web_search attempt %d failed: %s", attempt + 1, exc)
            await asyncio.sleep(0.5 * (attempt + 1))
    else:
        return f"Web search failed after {MAX_ATTEMPTS} attempts: {last_error}"

    if not results:
        return f"No web results found for: {params.query}"

    lines = [f"Web search results for '{params.query}':\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"**{i}. {r.get('title', 'Untitled')}**")
        lines.append(f"URL: {r.get('href', '')}")
        lines.append(r.get("body", ""))
        lines.append("")
    return "\n".join(lines)


SPEC = ToolSpec(
    name="web_search",
    label="Web Search",
    description=(
        "Search the internet for current, real-time information (news, sports, "
        "general questions, competitor info). Always cite the URL of each result used."
    ),
    category=ToolCategory.KNOWLEDGE,
    params_model=WebSearchParams,
    handler=_handler,
)
