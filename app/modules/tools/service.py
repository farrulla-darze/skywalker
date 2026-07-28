"""Tool registry and execution context.

A ToolSpec is a typed contract: name + description + Pydantic params model +
async handler. Handlers receive a ToolRunContext that carries the
*authenticated* user reference and shared services — tools never accept a
user identifier from the LLM (prevents cross-customer data access via
prompt injection).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.core.config import Settings

from .enums import ToolCategory
from .schemas import ToolInfoRead

if TYPE_CHECKING:
    from app.modules.knowledge.graph_store import Neo4jGraphStore
    from app.modules.knowledge.vector_store import QdrantVectorStore

# Handlers are declared per-tool with their concrete params model; the registry
# stores them type-erased (the runner validates params via the params_model).
ToolHandler = Callable[["ToolRunContext", Any], Awaitable[str]]


@dataclass
class ToolRunContext:
    """Per-run dependencies injected into every tool handler."""

    settings: Settings
    user_ref: str  # authenticated user id (or legacy external user_id)
    session_id: str
    vector_store: QdrantVectorStore | None = None
    graph_store: Neo4jGraphStore | None = None
    # Human-in-the-loop consultation: (question, context, agent_label) -> human's
    # answer text. Blocks the turn until the support staff replies on Telegram
    # (or timeout). agent_label names WHICH agent is asking, for the message.
    consult: Callable[[str, str, str], Awaitable[str]] | None = None
    # Display name of the agent currently executing (router or specialist);
    # maintained by the runner so tool handlers can attribute their actions.
    current_agent_label: str = ""
    # Streaming hooks (wired by the SSE pipeline): fire as each tool runs so
    # the frontend can show live progress during the "thinking" phase.
    on_step_start: Callable[[str, dict[str, Any] | None], Awaitable[None]] | None = None
    on_step_end: Callable[[Any], Awaitable[None]] | None = None  # receives StepRecord
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    """Typed definition of a tool."""

    name: str
    label: str
    description: str
    category: ToolCategory
    params_model: type[BaseModel]
    handler: ToolHandler

    def to_info(self) -> ToolInfoRead:
        return ToolInfoRead(
            name=self.name,
            label=self.label,
            description=self.description,
            category=self.category,
            parameters_json_schema=self.params_model.model_json_schema(),
        )


class ToolRegistry:
    """Central catalog of available tools."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def validate_names(self, names: list[str]) -> list[str]:
        """Return the subset of *names* that are unknown to the catalog."""
        return [n for n in names if n not in self._specs]


def build_default_registry() -> ToolRegistry:
    """Assemble the built-in tool catalog."""
    from .definitions import (
        account_ops,
        escalation,
        graph_search,
        rag_search,
        support_db,
        web_search,
    )

    registry = ToolRegistry()
    registry.register(rag_search.SPEC)
    registry.register(web_search.SPEC)
    registry.register(graph_search.SPEC)
    for spec in support_db.SPECS:
        registry.register(spec)
    for spec in account_ops.SPECS:
        registry.register(spec)
    registry.register(escalation.CONSULT_SPEC)
    return registry
