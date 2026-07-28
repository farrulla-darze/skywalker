"""Agents business logic — CRUD with catalog validation."""

import logging

from app.modules.tools.service import ToolRegistry

from .models import Agent
from .repository import AgentRepository
from .schemas import AgentCreate, AgentRead, AgentUpdate

logger = logging.getLogger(__name__)


class AgentServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentService:
    def __init__(self, repository: AgentRepository, tool_registry: ToolRegistry) -> None:
        self.repository = repository
        self.tool_registry = tool_registry

    def _validate_tools(self, tools: list[str]) -> None:
        unknown = self.tool_registry.validate_names(tools)
        if unknown:
            raise AgentServiceError(
                f"Unknown tools: {', '.join(unknown)}. "
                f"Available: {', '.join(self.tool_registry.names())}"
            )

    async def create(self, payload: AgentCreate, owner_id: str | None) -> AgentRead:
        self._validate_tools(payload.tools)
        if await self.repository.get_by_slug(payload.slug):
            raise AgentServiceError(f"Agent slug '{payload.slug}' already exists", 409)

        agent = Agent(
            owner_id=owner_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            instructions=payload.instructions,
            model=payload.model,
            kind=payload.kind,
            expose_as_tool=payload.expose_as_tool,
            enabled=payload.enabled,
            tools=payload.tools,
        )
        agent = await self.repository.create(agent)
        logger.info("Agent created: %s (%s)", agent.slug, agent.kind)
        return AgentRead.model_validate(agent)

    async def update(self, agent_id: str, payload: AgentUpdate) -> AgentRead:
        agent = await self.repository.get(agent_id)
        if agent is None:
            raise AgentServiceError("Agent not found", 404)

        data = payload.model_dump(exclude_unset=True)
        if "tools" in data and data["tools"] is not None:
            self._validate_tools(data["tools"])
        for key, value in data.items():
            setattr(agent, key, value)
        agent = await self.repository.save(agent)
        return AgentRead.model_validate(agent)

    async def delete(self, agent_id: str) -> None:
        agent = await self.repository.get(agent_id)
        if agent is None:
            raise AgentServiceError("Agent not found", 404)
        if agent.is_system:
            raise AgentServiceError(
                "System agents cannot be deleted — disable them instead", 400
            )
        await self.repository.delete(agent)

    async def list_all(self) -> list[AgentRead]:
        return [AgentRead.model_validate(a) for a in await self.repository.list_all()]

    async def get(self, agent_id: str) -> AgentRead:
        agent = await self.repository.get(agent_id)
        if agent is None:
            raise AgentServiceError("Agent not found", 404)
        return AgentRead.model_validate(agent)
