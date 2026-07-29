"""Chat HTTP layer.

Two surfaces:
- /api/v1/chat/*  — authenticated app API (frontend)
- /chat           — legacy challenge endpoint, accepts both payload shapes
                    ({message, user_id} and {question, userId})
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import CurrentUserDep, SessionDep, SettingsDep
from app.core.tracing import enqueue_for_review, score_session, score_trace
from app.modules.agents.repository import AgentRepository
from app.modules.chat.enums import ChatChannel, FeedbackRating, MessageRole
from app.modules.integrations.repository import IntegrationsRepository
from app.modules.integrations.service import TelegramService

from .models import ChatSession, MessageFeedback
from .repository import ChatRepository
from .schemas import (
    ChatMessageCreate,
    ChatMessageRead,
    ChatSessionCreate,
    ChatSessionRead,
    LegacyChatRequest,
    LegacyChatResponse,
    MessageFeedbackCreate,
    ReviewFlagCreate,
    SessionScoreCreate,
)
from .service import ChatService, ChatServiceError, EmitFn

chat_router = APIRouter(prefix="/chat", tags=["chat"])
legacy_router = APIRouter(tags=["legacy"])


def build_chat_service(request: Request, session, settings) -> ChatService:
    """Assemble the ChatService from a request (delegates to the state-based builder)."""
    return build_chat_service_from_state(request.app.state, session, settings)


def build_chat_service_from_state(state, session, settings) -> ChatService:
    """Assemble the ChatService from app state — usable by HTTP handlers AND the
    Telegram polling loop (which has no Request)."""
    telegram_service = TelegramService(IntegrationsRepository(session), settings)

    async def consultation_handler(
        chat_session,
        question: str,
        context: str,
        agent_label: str,
        emit: EmitFn | None = None,
    ) -> str:
        """Human-in-the-loop: post the question on Telegram and block for the reply.

        When *emit* is set (streaming turns), consultation progress is pushed to
        the chat UI: waiting (with elapsed seconds), answered, or timeout.
        """

        async def notify(event: dict) -> None:
            if emit is not None:
                await emit(event)

        # Resolve a human-readable customer display for the support message
        customer_display = chat_session.user_id or chat_session.external_ref or "anônimo"
        if chat_session.user_id:
            from app.modules.auth.repository import AuthRepository

            account = await AuthRepository(session).get_user_by_id(chat_session.user_id)
            if account:
                customer_display = f"{account.full_name} ({account.email})"

        consultation = await telegram_service.create_consultation(
            chat_session,
            question,
            context,
            agent_label=agent_label,
            customer_display=customer_display,
        )
        if consultation is None:
            return (
                "Human consultation channel is not available (Telegram not connected or "
                "no support chat set via /support_here). Do NOT invent an answer: tell "
                "the customer this needs a specialist and offer escalate_to_human."
            )
        await notify({"type": "consultation", "status": "waiting", "elapsed_s": 0})

        async def on_wait_tick(elapsed: float) -> None:
            await notify(
                {"type": "consultation", "status": "waiting", "elapsed_s": int(elapsed)}
            )

        answered = await telegram_service.wait_for_consultation_answer(
            consultation.id,
            state.db.session_factory,
            settings.consultation_timeout_seconds,
            on_wait_tick=on_wait_tick,
        )
        if answered is None:
            await notify({"type": "consultation", "status": "timeout"})
            return (
                f"No human reply within {settings.consultation_timeout_seconds}s "
                f"(consultation {consultation.id[:8]} stays open). Tell the customer a "
                "specialist will follow up shortly; do not guess the answer."
            )
        await notify(
            {
                "type": "consultation",
                "status": "answered",
                "answered_by": answered.answered_by,
            }
        )
        return (
            f"Human specialist (@{answered.answered_by}) replied:\n{answered.answer}\n\n"
            "If this settles the matter, use it to answer the customer (in your own "
            "words). If the specialist asked for more context or the reply is "
            "insufficient, call consult_human again as a follow-up."
        )

    return ChatService(
        repository=ChatRepository(session),
        agent_repository=AgentRepository(session),
        tool_registry=state.tool_registry,
        settings=settings,
        vector_store=getattr(state, "vector_store", None),
        graph_store=getattr(state, "graph_store", None),
        human_forward_handler=telegram_service.forward_to_human,
        consultation_handler=consultation_handler,
    )


# ---------------------------------------------------------------------------
# Authenticated app API
# ---------------------------------------------------------------------------


@chat_router.get("/sessions", response_model=list[ChatSessionRead])
async def list_sessions(
    request: Request, session: SessionDep, settings: SettingsDep, user: CurrentUserDep
):
    return await build_chat_service(request, session, settings).list_sessions(user.id)


@chat_router.post("/sessions", response_model=ChatSessionRead, status_code=201)
async def create_session(
    payload: ChatSessionCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    try:
        return await build_chat_service(request, session, settings).create_session(
            user_id=user.id, agent_id=payload.agent_id, title=payload.title
        )
    except ChatServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@chat_router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageRead])
async def list_messages(
    session_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    try:
        return await build_chat_service(request, session, settings).list_messages(
            session_id, user.id
        )
    except ChatServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@chat_router.post("/sessions/{session_id}/messages", response_model=ChatMessageRead)
async def send_message(
    session_id: str,
    payload: ChatMessageCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    service = build_chat_service(request, session, settings)
    try:
        chat_session = await service.get_owned_session(session_id, user.id)
        return await service.run_turn(chat_session, payload.content)
    except ChatServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@chat_router.post("/sessions/{session_id}/messages/stream")
async def send_message_streaming(
    session_id: str,
    payload: ChatMessageCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    """SSE stream of a chat turn: live tool steps, token deltas, final message."""
    # Ownership check on the request-scoped session (cheap, fails fast)
    try:
        await build_chat_service(request, session, settings).get_owned_session(
            session_id, user.id
        )
    except ChatServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # The turn itself runs on a DEDICATED DB session so it survives client
    # disconnects (closed tab, proxy timeout): messages persist and open human
    # consultations are still consumed. The session closes when the pipeline
    # ends (cleanup callback), not when the HTTP response ends.
    own_session = request.app.state.db.session_factory()
    try:
        service = build_chat_service_from_state(request.app.state, own_session, settings)
        chat_session = await service.get_owned_session(session_id, user.id)
    except Exception:
        await own_session.close()
        raise

    async def sse() -> AsyncIterator[str]:
        async for event in service.run_turn_streaming(
            chat_session, payload.content, cleanup=own_session.close
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _get_owned_assistant_message(service, message_id: str, user_id: str):
    message = await service.repository.get_message(message_id)
    if message is None or message.role != MessageRole.ASSISTANT:
        raise HTTPException(status_code=404, detail="Assistant message not found")
    try:
        await service.get_owned_session(message.session_id, user_id)
    except ChatServiceError as exc:
        raise HTTPException(status_code=404, detail="Assistant message not found") from exc
    return message


@chat_router.post("/messages/{message_id}/feedback", status_code=204)
async def submit_feedback(
    message_id: str,
    payload: MessageFeedbackCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    """Store feedback locally AND attach it as a Langfuse score on the exact trace."""
    service = build_chat_service(request, session, settings)
    message = await _get_owned_assistant_message(service, message_id, user.id)

    await service.repository.upsert_feedback(
        MessageFeedback(
            message_id=message_id,
            user_id=user.id,
            rating=FeedbackRating(payload.rating),
            comment=payload.comment,
        )
    )
    if message.trace_id:
        score_trace(
            message.trace_id,
            name="user-feedback",
            value=1.0 if payload.rating == FeedbackRating.UP else 0.0,
            comment=payload.comment,
            data_type="NUMERIC",
        )


@chat_router.post("/messages/{message_id}/review", status_code=202)
async def flag_message_for_review(
    message_id: str,
    payload: ReviewFlagCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    """Send this message's trace to the Langfuse 'chat-review' annotation queue."""
    service = build_chat_service(request, session, settings)
    message = await _get_owned_assistant_message(service, message_id, user.id)
    if not message.trace_id:
        raise HTTPException(
            status_code=409, detail="Message has no trace (observability was off)"
        )
    queued = enqueue_for_review(message.trace_id, comment=payload.comment)
    return {"queued": queued, "trace_id": message.trace_id}


@chat_router.post("/sessions/{session_id}/score", status_code=202)
async def score_chat_session(
    session_id: str,
    payload: SessionScoreCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
):
    """Attach a 1–5 rating (plus optional comment) to the whole Langfuse session."""
    service = build_chat_service(request, session, settings)
    try:
        await service.get_owned_session(session_id, user.id)
    except ChatServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    sent = score_session(
        session_id,
        name="session-rating",
        value=float(payload.rating),
        comment=payload.comment,
        data_type="NUMERIC",
    )
    return {"scored": sent, "session_id": session_id}


# ---------------------------------------------------------------------------
# Legacy challenge endpoint
# ---------------------------------------------------------------------------


@legacy_router.post("/chat", response_model=LegacyChatResponse)
async def legacy_chat(
    payload: LegacyChatRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
):
    if not settings.allow_anonymous_chat:
        raise HTTPException(
            status_code=401,
            detail="Anonymous chat is disabled. Use the authenticated /api/v1/chat API.",
        )
    service = build_chat_service(request, session, settings)

    chat_session = None
    if payload.session_id:
        chat_session = await service.repository.get_session(payload.session_id)
    if chat_session is None:
        chat_session = await service.repository.create_session(
            ChatSession(
                external_ref=payload.user_id,
                channel=ChatChannel.API,
                title=f"API session ({payload.user_id})",
            )
        )

    message = await service.run_turn(chat_session, payload.message)
    return LegacyChatResponse(
        sessionId=chat_session.id,
        response=message.content,
        metadata={
            "input_tokens": chat_session.input_tokens,
            "output_tokens": chat_session.output_tokens,
            "total_tokens": chat_session.input_tokens + chat_session.output_tokens,
        },
    )
