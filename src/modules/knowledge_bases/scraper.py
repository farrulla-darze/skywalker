"""Web scraper using crawl4ai for extracting webpage content as markdown."""

import re
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    """Result of scraping a single URL."""

    url: str
    markdown_content: str
    file_path: Path
    title: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class WebScraper:
    """Scrapes web pages and saves content as markdown files."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def scrape_url(self, url: str) -> ScrapeResult:
        """Scrape a single URL and save as markdown.

        Args:
            url: The URL to scrape.

        Returns:
            ScrapeResult with the markdown content and file path.
        """
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

        file_name = self._url_to_filename(url)
        file_path = self.output_dir / file_name

        try:
            async with AsyncWebCrawler() as crawler:
                config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
                result = await crawler.arun(url=url, config=config)

                if not result.success:
                    return ScrapeResult(
                        url=url,
                        markdown_content="",
                        file_path=file_path,
                        success=False,
                        error=result.error_message or "Crawl failed",
                    )

                markdown = result.markdown or ""
                title = result.metadata.get("title") if result.metadata else None

                # Save to file
                file_path.write_text(markdown, encoding="utf-8")
                logger.info("Scraped %s -> %s (%d chars)", url, file_path, len(markdown))

                return ScrapeResult(
                    url=url,
                    markdown_content=markdown,
                    file_path=file_path,
                    title=title,
                    success=True,
                )

        except Exception as e:
            logger.error("Failed to scrape %s: %s", url, e)
            return ScrapeResult(
                url=url,
                markdown_content="",
                file_path=file_path,
                success=False,
                error=str(e),
            )

    def _url_to_filename(self, url: str) -> str:
        """Convert URL to a safe filename."""
        # Remove protocol
        name = re.sub(r"https?://", "", url)
        # Replace non-alphanumeric with hyphens
        name = re.sub(r"[^a-zA-Z0-9]+", "-", name)
        # Strip leading/trailing hyphens and truncate
        name = name.strip("-")[:120]
        return f"{name}.md"
