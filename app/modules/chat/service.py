"""Chat business logic — the production message pipeline.

Pipeline per turn:
    input guardrail → (handoff check) → agent runner → output guardrail → persist

While a session is handed off to a human (state != BOT) the LLM is NOT called:
messages are stored and forwarded to the human channel.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from app.core.config import Settings
from app.modules.agents.models import Agent
from app.modules.agents.repository import AgentRepository
from app.modules.agents.runner import AgentRunner, HistoryTurn
from app.modules.guardrails.enums import GuardrailVerdictType
from app.modules.guardrails.service import GuardrailService
from app.modules.tools.service import ToolRegistry, ToolRunContext

from .enums import ChatChannel, HandoffState, MessageRole
from .models import ChatMessage, ChatSession
from .repository import ChatRepository
from .schemas import ChatMessageRead, ChatSessionRead, FeedbackRead

logger = logging.getLogger(__name__)

# Callback types wired by the integrations module
HumanForwardHandler = Callable[[ChatSession, str], Awaitable[None]]
EmitFn = Callable[[dict], Awaitable[None]]
# (session, question, context, agent_label, emit) -> human's answer text.
# *emit* is the live SSE event sink (None on non-streaming turns) so the
# handler can surface consultation progress to the chat UI.
ConsultationHandler = Callable[[ChatSession, str, str, str, EmitFn | None], Awaitable[str]]

# Interval between SSE keepalive pings when the pipeline produces no events
# (human consultation wait, non-streaming sub-agent runs, guardrail LLM calls).
# Keeps bytes on the wire so proxies don't cut the idle connection.
STREAM_KEEPALIVE_SECONDS = 15.0

_HANDOFF_ACK = (
    "Um atendente humano está cuidando desta conversa. Sua mensagem foi encaminhada."
)


class ChatServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        agent_repository: AgentRepository,
        tool_registry: ToolRegistry,
        settings: Settings,
        guardrail_service: GuardrailService | None = None,
        vector_store=None,
        graph_store=None,
        human_forward_handler: HumanForwardHandler | None = None,
        consultation_handler: ConsultationHandler | None = None,
    ) -> None:
        self.repository = repository
        self.agent_repository = agent_repository
        self.tool_registry = tool_registry
        self.settings = settings
        self.guardrail_service = guardrail_service or GuardrailService(settings)
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.human_forward_handler = human_forward_handler
        self.consultation_handler = consultation_handler

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(
        self,
        user_id: str | None,
        agent_id: str | None = None,
        channel: ChatChannel = ChatChannel.WEB,
        external_ref: str | None = None,
        title: str | None = None,
    ) -> ChatSessionRead:
        if agent_id and await self.agent_repository.get(agent_id) is None:
            raise ChatServiceError("Agent not found", 404)
        session = ChatSession(
            user_id=user_id,
            external_ref=external_ref,
            channel=channel,
            agent_id=agent_id,
            title=title or "New conversation",
        )
        session = await self.repository.create_session(session)
        return ChatSessionRead.model_validate(session)

    async def list_sessions(self, user_id: str) -> list[ChatSessionRead]:
        sessions = await self.repository.list_sessions_for_user(user_id)
        return [ChatSessionRead.model_validate(s) for s in sessions]

    async def get_owned_session(self, session_id: str, user_id: str | None) -> ChatSession:
        session = await self.repository.get_session(session_id)
        if session is None:
            raise ChatServiceError("Session not found", 404)
        # Ownership check: authenticated sessions belong to their creator
        if session.user_id is not None and session.user_id != user_id:
            raise ChatServiceError("Session not found", 404)
        return session

    async def list_messages(self, session_id: str, user_id: str | None) -> list[ChatMessageRead]:
        session = await self.get_owned_session(session_id, user_id)
        messages = await self.repository.list_messages(session.id)
        feedback = await self.repository.get_feedback_for_messages([m.id for m in messages])
        reads = []
        for m in messages:
            read = ChatMessageRead.model_validate(m)
            if m.id in feedback:
                read.feedback = FeedbackRead.model_validate(feedback[m.id])
            reads.append(read)
        return reads

    # ------------------------------------------------------------------
    # The turn pipeline
    # ------------------------------------------------------------------

    async def run_turn(self, session: ChatSession, content: str) -> ChatMessageRead:
        """One chat turn, wrapped in a Langfuse root span (no-op when disabled)."""
        from app.core.tracing import chat_turn_span, current_trace_id

        with chat_turn_span(
            session_id=session.id,
            user_ref=session.user_id or session.external_ref or "anonymous",
            channel=session.channel,
            user_message=content,
        ) as span:
            result = await self._run_turn(session, content, trace_id=current_trace_id())
            if span is not None:
                try:
                    span.update(
                        output={
                            "response": result.content,
                            "tools": [s.tool for s in (result.steps or [])],
                        }
                    )
                except Exception:  # noqa: BLE001 — tracing must never break a turn
                    logger.debug("chat_turn span update failed", exc_info=True)
            return result

    async def run_turn_streaming(
        self,
        session: ChatSession,
        content: str,
        cleanup: Callable[[], Awaitable[None]] | None = None,
    ) -> AsyncIterator[dict]:
        """Streaming variant of the turn pipeline, yielding SSE-ready events.

        Event types: step_started, step_finished, token, revised, done, error.
        The pipeline runs as a task pushing into a queue so tool events surface
        live while the model is still working.

        Disconnect resilience: if the SSE consumer goes away mid-turn (closed
        tab, proxy timeout), the pipeline is NOT cancelled — it finishes in the
        background so messages persist and any open human consultation is still
        consumed. For that to be safe the service must be built on a DEDICATED
        DB session whose closure is passed as *cleanup* (invoked when the
        pipeline actually ends), not on a request-scoped session.
        """
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        async def pipeline() -> None:
            from app.core.tracing import chat_turn_span, current_trace_id

            try:
                with chat_turn_span(
                    session_id=session.id,
                    user_ref=session.user_id or session.external_ref or "anonymous",
                    channel=session.channel,
                    user_message=content,
                ) as span:
                    message = await self._run_turn(
                        session, content, trace_id=current_trace_id(), emit=emit
                    )
                    if span is not None:
                        try:
                            span.update(
                                output={
                                    "response": message.content,
                                    "tools": [s.tool for s in (message.steps or [])],
                                }
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug("chat_turn span update failed", exc_info=True)
                await emit({"type": "done", "message": message.model_dump(mode="json")})
            except Exception as exc:  # noqa: BLE001
                logger.error("Streaming turn failed: %s", exc, exc_info=True)
                await emit({"type": "error", "detail": str(exc)})
            finally:
                await queue.put(None)  # sentinel
                if cleanup is not None:
                    try:
                        await cleanup()
                    except Exception:  # noqa: BLE001
                        logger.debug("Streaming cleanup failed", exc_info=True)

        task = asyncio.create_task(pipeline())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=STREAM_KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    yield {"type": "ping"}
                    continue
                if event is None:
                    break
                yield event
            await task
        finally:
            if not task.done():
                # Consumer disconnected mid-turn — detach, don't cancel.
                logger.warning(
                    "SSE client disconnected; turn for session %s continues in background",
                    session.id,
                )

    async def _run_turn(
        self,
        session: ChatSession,
        content: str,
        trace_id: str | None = None,
        emit: EmitFn | None = None,
    ) -> ChatMessageRead:
        """Shared pipeline. When *emit* is set, live events are produced and the
        final answer is streamed token-by-token; otherwise a single blocking run."""
        await self.repository.add_message(
            ChatMessage(session_id=session.id, role=MessageRole.USER, content=content)
        )

        # Auto-title the session from the first message
        if session.title == "New conversation":
            session.title = content[:60] + ("…" if len(content) > 60 else "")
            await self.repository.save_session(session)

        # Handoff: while a human owns the conversation, the LLM stays out
        if session.handoff_state != HandoffState.BOT:
            if self.human_forward_handler:
                try:
                    await self.human_forward_handler(session, content)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Human-forward failed: %s", exc)
            assistant = await self.repository.add_message(
                ChatMessage(
                    session_id=session.id, role=MessageRole.SYSTEM, content=_HANDOFF_ACK
                )
            )
            return ChatMessageRead.model_validate(assistant)

        # Input guardrail
        if emit:
            await emit({"type": "step_started", "tool": "guardrail:input"})
        verdict = await self.guardrail_service.validate_input(content)
        if emit:
            await emit(
                {"type": "step_finished", "tool": "guardrail:input",
                 "result_preview": verdict.reason}
            )
        if verdict.verdict == GuardrailVerdictType.BLOCK:
            logger.warning("Input blocked by guardrail: %s", verdict.reason)
            assistant = await self.repository.add_message(
                ChatMessage(
                    session_id=session.id,
                    role=MessageRole.ASSISTANT,
                    content=verdict.safe_response
                    or "Não posso ajudar com isso. Posso ajudar com produtos Getnet?",
                    steps=[{"tool": "guardrail:input", "result_preview": verdict.reason}],
                    trace_id=trace_id,
                )
            )
            return ChatMessageRead.model_validate(assistant)

        # Resolve agent (session-specific or default router)
        agent = await self._resolve_agent(session)
        specialists = await self.agent_repository.list_enabled_specialists()

        ctx = ToolRunContext(
            settings=self.settings,
            user_ref=session.user_id or session.external_ref or "anonymous",
            session_id=session.id,
            vector_store=self.vector_store,
            graph_store=self.graph_store,
            consult=self._make_consult(session, emit),
            on_step_start=(
                (lambda tool, args: emit({"type": "step_started", "tool": tool, "args": args}))
                if emit
                else None
            ),
            on_step_end=(
                (
                    lambda record: emit(
                        {"type": "step_finished", **record.model_dump(exclude_none=True)}
                    )
                )
                if emit
                else None
            ),
        )

        history = [
            HistoryTurn(role=m.role, content=m.content)
            for m in await self.repository.list_messages(session.id)
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ][:-1]  # exclude the message we just stored (it goes as the prompt)

        runner = AgentRunner(self.settings, self.tool_registry, specialists)
        try:
            if emit:

                async def on_token(delta: str) -> None:
                    await emit({"type": "token", "delta": delta})

                outcome = await runner.run_streaming(agent, content, history, ctx, on_token)
            else:
                outcome = await runner.run(agent, content, history, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.error("Agent run failed: %s", exc, exc_info=True)
            assistant = await self.repository.add_message(
                ChatMessage(
                    session_id=session.id,
                    role=MessageRole.ASSISTANT,
                    content="Desculpe, tive um problema para processar sua mensagem. "
                    "Tente novamente em instantes.",
                    steps=[{"tool": "error", "result_preview": str(exc)[:400]}],
                    trace_id=trace_id,
                )
            )
            return ChatMessageRead.model_validate(assistant)

        # Output guardrail. In streaming mode the text was already shown; if the
        # guardrail blocks, a 'revised' event replaces the displayed content.
        out_verdict = await self.guardrail_service.validate_output(outcome.text, content)
        final_text = outcome.text
        steps = [s.model_dump(exclude_none=True) for s in outcome.steps]
        if out_verdict.verdict == GuardrailVerdictType.BLOCK:
            logger.warning("Output revised by guardrail: %s", out_verdict.reason)
            final_text = out_verdict.safe_response or final_text
            steps.append({"tool": "guardrail:output", "result_preview": out_verdict.reason})
            if emit:
                await emit({"type": "revised", "content": final_text})

        assistant = await self.repository.add_message(
            ChatMessage(
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content=final_text,
                steps=steps,
                usage={
                    "input_tokens": outcome.input_tokens,
                    "output_tokens": outcome.output_tokens,
                },
                trace_id=trace_id,
            )
        )
        session.input_tokens += outcome.input_tokens
        session.output_tokens += outcome.output_tokens
        await self.repository.save_session(session)

        return ChatMessageRead.model_validate(assistant)

    async def _resolve_agent(self, session: ChatSession) -> Agent:
        if session.agent_id:
            agent = await self.agent_repository.get(session.agent_id)
            if agent and agent.enabled:
                return agent
        router = await self.agent_repository.get_default_router()
        if router is None:
            raise ChatServiceError("No enabled router agent configured", 503)
        return router

    def _make_consult(self, session: ChatSession, emit: EmitFn | None = None):
        """Human-in-the-loop consultation — the agent stays in charge (no handoff)."""
        handler = self.consultation_handler
        if handler is None:
            return None

        async def consult(question: str, context: str, agent_label: str) -> str:
            return await handler(session, question, context, agent_label, emit)

        return consult
