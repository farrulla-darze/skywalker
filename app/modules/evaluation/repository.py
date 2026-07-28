"""Evaluation persistence layer."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EvalResult, EvalRun, GoldenItem


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Golden items -----------------------------------------------------

    async def create_item(self, item: GoldenItem) -> GoldenItem:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_item(self, item_id: str) -> GoldenItem | None:
        return await self.session.get(GoldenItem, item_id)

    async def list_items(self, include_archived: bool = False) -> list[GoldenItem]:
        query = select(GoldenItem).order_by(GoldenItem.created_at.asc())
        if not include_archived:
            query = query.where(GoldenItem.archived.is_(False))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def save_item(self, item: GoldenItem) -> GoldenItem:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def count_items(self) -> int:
        result = await self.session.execute(select(GoldenItem))
        return len(list(result.scalars().all()))

    # --- Runs -------------------------------------------------------------

    async def create_run(self, run: EvalRun) -> EvalRun:
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get_run(self, run_id: str) -> EvalRun | None:
        return await self.session.get(EvalRun, run_id)

    async def list_runs(self, limit: int = 50) -> list[EvalRun]:
        result = await self.session.execute(
            select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def save_run(self, run: EvalRun) -> EvalRun:
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def add_result(self, result: EvalResult) -> EvalResult:
        self.session.add(result)
        await self.session.commit()
        return result

    async def list_results(self, run_id: str) -> list[EvalResult]:
        result = await self.session.execute(
            select(EvalResult).where(EvalResult.run_id == run_id)
        )
        return list(result.scalars().all())
