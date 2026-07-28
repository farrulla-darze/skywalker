"""Regression test: IngestionJob.url_statuses must persist in-place mutations.

Bug history: the ingestion pipeline builds `statuses = list(job.url_statuses)`
once, then repeatedly does `statuses[i] = {...}` (in-place list mutation) and
reassigns `job.url_statuses = statuses` after every URL. Because `statuses`
keeps the same object identity across iterations, a plain JSON column never
detects the change after the first assignment — polling the job showed all
URLs after the first stuck at "pending" even though ingestion succeeded and
data landed in the vector store. Fixed via MutableList.as_mutable(JSON).
"""

import pytest

from app.core.db import Database
from app.modules.knowledge.models import IngestionJob
from app.modules.knowledge.repository import KnowledgeRepository

pytestmark = pytest.mark.anyio

URLS = ["https://a.io", "https://b.io", "https://c.io"]


@pytest.fixture
async def db():
    database = Database("sqlite+aiosqlite://")
    await database.create_all()
    yield database
    await database.dispose()


async def test_in_place_url_statuses_updates_persist_across_saves(db):
    async with db.session_factory() as session:
        job = await KnowledgeRepository(session).create_job(
            IngestionJob(
                namespace="test",
                urls=URLS,
                url_statuses=[
                    {"url": u, "status": "pending", "chunks_count": 0, "error": None}
                    for u in URLS
                ],
            )
        )
        job_id = job.id

        # Simulate the pipeline: mutate the SAME list object across multiple saves,
        # exactly like run_ingestion_pipeline does — one save per URL processed.
        statuses = list(job.url_statuses)
        repository = KnowledgeRepository(session)
        for i in range(len(URLS)):
            statuses[i] = {**statuses[i], "status": "completed", "chunks_count": i + 1}
            job.url_statuses = statuses
            await repository.save(job)

    # Re-fetch from a brand new session to rule out identity-map masking the bug.
    async with db.session_factory() as fresh_session:
        reloaded = await KnowledgeRepository(fresh_session).get_job(job_id)

    assert reloaded is not None
    statuses_by_url = {s["url"]: s for s in reloaded.url_statuses}
    for i, url in enumerate(URLS):
        assert statuses_by_url[url]["status"] == "completed", (
            f"{url} did not persist its status update — url_statuses mutation bug regressed"
        )
        assert statuses_by_url[url]["chunks_count"] == i + 1
