"""Knowledge module enums."""

from enum import StrEnum


class IngestStatus(StrEnum):
    PENDING = "pending"
    SCRAPING = "scraping"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"
