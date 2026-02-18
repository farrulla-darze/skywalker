"""
Web search tool - Search the internet for information.

Uses DuckDuckGo search API to find information from the web.
"""

import asyncio
import logging
import time
from pathlib import Path
from threading import Event
from typing import Optional
from pydantic import BaseModel, Field
from ddgs import DDGS

from .schema import ToolResult, TextContent, AgentTool

logger = logging.getLogger(__name__)

# Constants
SEARCH_TIMEOUT = 30.0
MAX_RESULTS = 5

# Global semaphore to prevent parallel web searches (DuckDuckGo has issues with concurrent requests)
_web_search_semaphore = asyncio.Semaphore(1)  # Only allow one search at a time


class WebSearchParams(BaseModel):
    """Input parameters for the web_search tool."""

    query: str = Field(
        ...,
        description="Search query to look up on the internet",
        examples=["CloudWalk payment gateway features", "latest cryptocurrency trends 2026"]
    )

    max_results: Optional[int] = Field(
        default=MAX_RESULTS,
        description="Maximum number of search results to return (default: 5)",
        ge=1,
        le=10
    )

    class Config:
        extra = "forbid"
        use_enum_values = True


async def _execute_web_search_tool(
    tool_call_id: str,
    params: WebSearchParams,
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the web search tool operation.

    Uses DuckDuckGo search API to fetch results.

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

    # Use semaphore to prevent parallel web searches (causes hangs)
    async with _web_search_semaphore:
        query_preview = params.query[:80] + "..." if len(params.query) > 80 else params.query
        logger.info(f"[PERF] web_search acquired semaphore: query='{query_preview}'")

        try:
            # Use DuckDuckGo search library
            max_results = params.max_results or MAX_RESULTS
            logger.info(f"[PERF] web_search started: query='{query_preview}', max_results={max_results}")

            # Run search in thread pool since DDGS is synchronous
            loop = asyncio.get_event_loop()

            def _search():
                search_start = time.time()
                if signal and signal.is_set():
                    raise Exception("Operation aborted")

                with DDGS() as ddgs:
                    results = list(ddgs.text(
                        query=params.query,
                        max_results=max_results
                    ))
                search_duration = time.time() - search_start
                logger.info(f"[PERF] DuckDuckGo API call completed: duration={search_duration:.2f}s, results={len(results)}")
                return results

            # Add timeout to prevent hanging searches
            try:
                results = await asyncio.wait_for(
                    loop.run_in_executor(None, _search),
                    timeout=SEARCH_TIMEOUT
                )
            except asyncio.TimeoutError:
                total_duration = time.time() - start_time
                logger.warning(f"[PERF] web_search timed out after {SEARCH_TIMEOUT}s: query='{query_preview}'")
                return ToolResult(
                    content=[TextContent(text=f"Web search timed out after {SEARCH_TIMEOUT} seconds. Please try again with a more specific query.")],
                    details={"error": "timeout", "duration_seconds": round(total_duration, 2), "timeout_seconds": SEARCH_TIMEOUT}
                )

            if signal and signal.is_set():
                raise Exception("Operation aborted")

            if not results:
                output_text = f"No results found for: {params.query}"
            else:
                output_text = f"Search results for '{params.query}':\n\n"
                for i, result in enumerate(results, 1):
                    title = result.get('title', 'No title')
                    url = result.get('href', result.get('url', ''))
                    snippet = result.get('body', result.get('snippet', ''))

                    output_text += f"{i}. **{title}**\n"
                    output_text += f"   URL: {url}\n"
                    if snippet:
                        output_text += f"   {snippet}\n"
                    output_text += "\n"

            total_duration = time.time() - start_time
            logger.info(f"[PERF] web_search completed: total_duration={total_duration:.2f}s, results={len(results)}")

            return ToolResult(
                content=[TextContent(text=output_text)],
                details={"query": params.query, "results_count": len(results), "duration_seconds": round(total_duration, 2)}
            )

        except Exception as e:
            total_duration = time.time() - start_time
            logger.error(f"[PERF] web_search failed: duration={total_duration:.2f}s, query='{query_preview}', error={e}")
            error_msg = f"Web search failed: {str(e)}"
            return ToolResult(
                content=[TextContent(text=error_msg)],
                details={"error": str(e), "duration_seconds": round(total_duration, 2)}
            )


def create_web_search_tool() -> AgentTool:
    """
    Create a web search tool for internet searches.

    Returns:
        AgentTool descriptor for the web search tool
    """
    async def execute(
        tool_call_id: str,
        params: WebSearchParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the web search tool."""
        return await _execute_web_search_tool(
            tool_call_id,
            params,
            signal,
        )

    return AgentTool(
        name="web_search",
        label="web_search",
        description=(
            "Search the internet for information using DuckDuckGo. "
            "Use this tool when you need to find current information, news, "
            "or general knowledge that may not be in the knowledge base. "
            "Returns up to 10 search results with titles, URLs, and snippets."
        ),
        parameters_schema=WebSearchParams,
        execute=execute,
    )
