"""Agents persistence layer."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import AgentKind
from .models import Agent


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, agent: Agent) -> Agent:
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def get(self, agent_id: str) -> Agent | None:
        return await self.session.get(Agent, agent_id)

    async def get_by_slug(self, slug: str) -> Agent | None:
        result = await self.session.execute(select(Agent).where(Agent.slug == slug))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Agent]:
        result = await self.session.execute(select(Agent).order_by(Agent.created_at.asc()))
        return list(result.scalars().all())

    async def get_default_router(self) -> Agent | None:
        result = await self.session.execute(
            select(Agent)
            .where(Agent.kind == AgentKind.ROUTER, Agent.enabled.is_(True))
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_enabled_specialists(self) -> list[Agent]:
        result = await self.session.execute(
            select(Agent).where(
                Agent.kind == AgentKind.SPECIALIST,
                Agent.enabled.is_(True),
                Agent.expose_as_tool.is_(True),
            )
        )
        return list(result.scalars().all())

    async def save(self, agent: Agent) -> Agent:
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def delete(self, agent: Agent) -> None:
        await self.session.delete(agent)
        await self.session.commit()
