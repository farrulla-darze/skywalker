"""Knowledge persistence layer (ingestion jobs)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IngestionJob


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(self, job: IngestionJob) -> IngestionJob:
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_job(self, job_id: str) -> IngestionJob | None:
        return await self.session.get(IngestionJob, job_id)

    async def list_jobs(self, limit: int = 50) -> list[IngestionJob]:
        result = await self.session.execute(
            select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def save(self, job: IngestionJob) -> None:
        self.session.add(job)
        await self.session.commit()
