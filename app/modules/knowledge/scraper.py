"""Web scraper — fetches a URL and extracts main content as markdown.

Uses httpx + trafilatura (no headless browser required), which keeps the
Docker image light and works in any environment.
"""

import logging
from dataclasses import dataclass

import httpx
import trafilatura

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; SkywalkerBot/1.0; +https://github.com/farrulla)"


@dataclass
class ScrapeResult:
    url: str
    success: bool
    markdown: str = ""
    error: str | None = None


class WebScraper:
    """Fetch + extract pipeline for knowledge base ingestion."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def scrape_url(self, url: str) -> ScrapeResult:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Scrape failed for %s: %s", url, exc)
            return ScrapeResult(url=url, success=False, error=str(exc))

        markdown = trafilatura.extract(
            response.text,
            url=url,
            output_format="markdown",
            include_tables=True,
            include_links=False,
        )
        if not markdown or not markdown.strip():
            return ScrapeResult(url=url, success=False, error="No extractable content")

        return ScrapeResult(url=url, success=True, markdown=markdown)
