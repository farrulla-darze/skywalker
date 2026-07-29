"""Agent execution runner — thin, correct layer over pydantic-ai.

This replaces the v1 AgentExecutor/BaseAgent/AgentManager triplet and fixes
the three execution bugs of the original implementation:

- Instructions are passed through pydantic-ai's public ``instructions``
  parameter (v1 assigned a nonexistent private attribute, so sub-agent
  prompts never reached the model).
- Conversation history is rebuilt into real ``ModelMessage`` objects and
  passed as ``message_history`` (v1 always passed ``[]``).
- Token usage comes from ``result.usage()`` (v1 estimated ``len(text)//4``).

Specialist agents are exposed to the router as tools ("agent-as-tool");
their tool calls are recorded as nested steps.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.settings import ModelSettings

from app.core.config import Settings
from app.modules.tools.schemas import StepRecord
from app.modules.tools.service import ToolRegistry, ToolRunContext, ToolSpec

from .models import Agent

logger = logging.getLogger(__name__)

RESULT_PREVIEW_CHARS = 400
MAX_HISTORY_MESSAGES = 30


class DelegateParams(BaseModel):
    """Input schema when a specialist agent is invoked as a tool."""

    query: str = Field(description="The question or task to delegate to this agent")


@dataclass
class RunOutcome:
    text: str
    steps: list[StepRecord] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class HistoryTurn:
    role: str  # "user" | "assistant"
    content: str


class AgentRunner:
    """Builds and runs a pydantic-ai agent from a DB agent definition."""

    def __init__(
        self,
        settings: Settings,
        tool_registry: ToolRegistry,
        specialists: list[Agent] | None = None,
    ) -> None:
        self.settings = settings
        self.tool_registry = tool_registry
        self.specialists = specialists or []

    async def run(
        self,
        agent: Agent,
        user_message: str,
        history: list[HistoryTurn],
        ctx: ToolRunContext,
    ) -> RunOutcome:
        steps: list[StepRecord] = []
        ctx.current_agent_label = agent.name
        pyd_agent, prompt_client = self._build_agent(agent, ctx, steps, include_specialists=True)

        with self._prompt_link(prompt_client):
            result = await pyd_agent.run(
                user_message,
                message_history=self._build_message_history(history),
            )

        usage = result.usage() if callable(result.usage) else result.usage
        input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "request_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", None) or getattr(
            usage, "response_tokens", 0
        )

        return RunOutcome(
            text=result.output,
            steps=steps,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
        )

    async def run_streaming(
        self,
        agent: Agent,
        user_message: str,
        history: list[HistoryTurn],
        ctx: ToolRunContext,
        on_token: Callable[[str], Awaitable[None]],
    ) -> RunOutcome:
        """Like ``run`` but streams the final answer token-by-token via *on_token*.

        Tool executions happen during the loop (before the final text starts);
        live step events fire through ``ctx.on_step_start`` / ``ctx.on_step_end``.
        """
        steps: list[StepRecord] = []
        ctx.current_agent_label = agent.name
        pyd_agent, prompt_client = self._build_agent(agent, ctx, steps, include_specialists=True)

        text_parts: list[str] = []
        with self._prompt_link(prompt_client):
            async with pyd_agent.run_stream(
                user_message,
                message_history=self._build_message_history(history),
            ) as stream:
                async for delta in stream.stream_text(delta=True):
                    text_parts.append(delta)
                    await on_token(delta)
                usage = stream.usage() if callable(stream.usage) else stream.usage

        input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "request_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", None) or getattr(
            usage, "response_tokens", 0
        )
        return RunOutcome(
            text="".join(text_parts),
            steps=steps,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
        )

    # ------------------------------------------------------------------
    # Agent assembly
    # ------------------------------------------------------------------

    def _build_agent(
        self,
        agent: Agent,
        ctx: ToolRunContext,
        steps: list[StepRecord],
        include_specialists: bool,
    ) -> tuple[PydanticAgent, Any]:
        from .prompts import resolve_agent_instructions

        model = agent.model or self.settings.default_model
        instructions, prompt_client = resolve_agent_instructions(agent)
        pyd_agent = PydanticAgent(
            model=model,
            instructions=(instructions, self._runtime_context(ctx)),
            model_settings=ModelSettings(timeout=self.settings.llm_request_timeout_seconds),
        )

        for tool_name in agent.tools or []:
            spec = self.tool_registry.get(tool_name)
            if spec is None:
                logger.warning("Agent '%s' references unknown tool '%s'", agent.slug, tool_name)
                continue
            self._register_tool(pyd_agent, spec, ctx, steps)

        if include_specialists and agent.kind == "router":
            for specialist in self.specialists:
                self._register_specialist(pyd_agent, specialist, ctx, steps)

        return pyd_agent, prompt_client

    @staticmethod
    def _prompt_link(prompt_client: Any):
        """Link this run's generations to the Langfuse prompt version (if any)."""
        if prompt_client is None:
            return nullcontext()
        try:
            from langfuse import propagate_attributes

            return propagate_attributes(prompt=prompt_client)
        except Exception:  # noqa: BLE001
            return nullcontext()

    def _runtime_context(self, ctx: ToolRunContext) -> str:
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"Runtime context — current date/time: {now}. "
            f"You are talking to the authenticated customer '{ctx.user_ref}' "
            f"(session {ctx.session_id}). Reply in the same language the customer uses."
        )

    def _register_tool(
        self,
        pyd_agent: PydanticAgent,
        spec: ToolSpec,
        ctx: ToolRunContext,
        steps: list[StepRecord],
    ) -> None:
        params_model = spec.params_model
        handler = spec.handler

        async def tool_fn(params: params_model) -> str:  # type: ignore[valid-type]
            args = params.model_dump(exclude_none=True)  # type: ignore[attr-defined]
            if ctx.on_step_start:
                await ctx.on_step_start(spec.name, args)
            start = time.monotonic()
            try:
                result_text = await handler(ctx, params)
            except Exception as exc:  # noqa: BLE001 — errors return to the LLM as text
                logger.error("Tool '%s' failed: %s", spec.name, exc, exc_info=True)
                result_text = f"Error in {spec.name}: {exc}"
            duration_ms = int((time.monotonic() - start) * 1000)
            record = StepRecord(
                tool=spec.name,
                args=args,
                result_preview=result_text[:RESULT_PREVIEW_CHARS],
                duration_ms=duration_ms,
            )
            steps.append(record)
            if ctx.on_step_end:
                await ctx.on_step_end(record)
            return result_text

        tool_fn.__name__ = spec.name
        # Runtime signature is (func, /, *, name=..., description=...); mypy's
        # overloads only model the pure-decorator forms.
        pyd_agent.tool_plain(  # type: ignore[call-overload]
            tool_fn, name=spec.name, description=spec.description
        )

    def _register_specialist(
        self,
        pyd_agent: PydanticAgent,
        specialist: Agent,
        ctx: ToolRunContext,
        steps: list[StepRecord],
    ) -> None:
        async def delegate_fn(params: DelegateParams) -> str:
            step_name = f"agent:{specialist.slug}"
            if ctx.on_step_start:
                await ctx.on_step_start(step_name, {"query": params.query})
            start = time.monotonic()
            nested_steps: list[StepRecord] = []
            sub_agent, sub_prompt = self._build_agent(
                specialist, ctx, nested_steps, include_specialists=False
            )
            previous_label = ctx.current_agent_label
            ctx.current_agent_label = specialist.name
            try:
                # Specialists run stateless on the delegated query; the router
                # owns conversation continuity.
                with self._prompt_link(sub_prompt):
                    result = await sub_agent.run(params.query)
                result_text = result.output
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Specialist '%s' failed: %s", specialist.slug, exc, exc_info=True
                )
                result_text = f"Specialist '{specialist.slug}' failed: {exc}"
            finally:
                ctx.current_agent_label = previous_label

            duration_ms = int((time.monotonic() - start) * 1000)
            record = StepRecord(
                tool=step_name,
                args={"query": params.query},
                result_preview=result_text[:RESULT_PREVIEW_CHARS],
                duration_ms=duration_ms,
                nested_steps=nested_steps or None,
            )
            steps.append(record)
            if ctx.on_step_end:
                await ctx.on_step_end(record)
            return result_text

        delegate_fn.__name__ = specialist.slug.replace("-", "_")
        pyd_agent.tool_plain(  # type: ignore[call-overload]
            delegate_fn,
            name=delegate_fn.__name__,
            description=(
                f"Delegate to the '{specialist.name}' agent. {specialist.description}"
            ),
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    @staticmethod
    def _build_message_history(history: list[HistoryTurn]) -> list[ModelMessage]:
        messages: list[ModelMessage] = []
        for turn in history[-MAX_HISTORY_MESSAGES:]:
            if turn.role == "user":
                messages.append(ModelRequest(parts=[UserPromptPart(content=turn.content)]))
            elif turn.role == "assistant":
                messages.append(ModelResponse(parts=[TextPart(content=turn.content)]))
        return messages
