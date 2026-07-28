"""Langfuse tracing, scores and annotation.

Layers of instrumentation:

1. ``pydantic_ai.Agent.instrument_all()`` — emits OpenTelemetry spans for every
   model request and every tool call (name, args, result, tokens, latency).
   The Langfuse SDK (v3+, OTel-based) installs the tracer provider that
   captures them.
2. A root ``chat_turn`` span per message (see ``chat_turn_span``) that carries
   the Langfuse trace attributes — session_id, user_id, channel — so traces
   group by conversation and user in the Langfuse UI.
3. Score/annotation helpers so user feedback given in the chat frontend lands
   in Langfuse attached to the exact trace (message) or session it refers to,
   where it is visible and editable alongside the trace.

Every helper is a silent no-op when tracing is disabled — observability must
never break the product path.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from .config import Settings

logger = logging.getLogger(__name__)

_initialized = False

REVIEW_QUEUE_NAME = "chat-review"


def is_tracing_enabled() -> bool:
    return _initialized


def setup_tracing(settings: Settings) -> bool:
    """Initialize Langfuse + pydantic-ai instrumentation. Safe to call twice."""
    global _initialized
    if not settings.langfuse_enabled:
        return False
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("Langfuse enabled but keys missing — tracing disabled")
        return False
    if _initialized:
        return True

    try:
        from langfuse import Langfuse
        from pydantic_ai import Agent

        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        Agent.instrument_all()
        _initialized = True
        logger.info("Langfuse tracing enabled (host=%s)", settings.langfuse_host)
        return True
    except Exception as exc:  # noqa: BLE001 — observability must never break the app
        logger.error("Failed to initialize Langfuse tracing: %s", exc)
        return False


def shutdown_tracing() -> None:
    """Flush pending spans on application shutdown."""
    if not _initialized:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:  # noqa: BLE001
        logger.debug("Langfuse flush failed on shutdown", exc_info=True)


def current_trace_id() -> str | None:
    """Trace id of the currently active span context (None when disabled)."""
    if not _initialized:
        return None
    try:
        from langfuse import get_client

        return get_client().get_current_trace_id()
    except Exception:  # noqa: BLE001
        return None


@contextmanager
def chat_turn_span(
    *,
    session_id: str,
    user_ref: str,
    channel: str,
    user_message: str,
) -> Iterator[Any]:
    """Root span for one chat turn. Yields the span (or None when disabled).

    All pydantic-ai spans created inside (model requests, tool calls, guardrail
    and extraction agents) nest under this span via OTel context propagation.
    """
    if not _initialized:
        yield None
        return

    try:
        from langfuse import get_client, propagate_attributes

        langfuse = get_client()
    except Exception:  # noqa: BLE001
        yield None
        return

    # propagate_attributes stamps session/user/tags on the root span AND every
    # child span (model requests, tool calls, guardrails) created inside it —
    # this is what groups traces by conversation/user in the Langfuse UI.
    with langfuse.start_as_current_observation(
        name="chat_turn", as_type="agent", input={"message": user_message}
    ) as span:
        with propagate_attributes(
            user_id=user_ref,
            session_id=session_id,
            tags=[f"channel:{channel}"],
            trace_name="chat_turn",
        ):
            yield span


# ---------------------------------------------------------------------------
# Scores & annotation (frontend feedback → Langfuse)
# ---------------------------------------------------------------------------


ScoreDataType = Literal["NUMERIC", "CATEGORICAL", "BOOLEAN", "TEXT"]


def _create_score(**kwargs: Any) -> bool:
    """Best-effort create_score wrapper (create_score's overloads pair value
    type with data_type; we pass through dynamically)."""
    if not _initialized:
        return False
    try:
        from langfuse import get_client

        get_client().create_score(**kwargs)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create Langfuse score %s: %s", kwargs.get("name"), exc)
        return False


def score_trace(
    trace_id: str,
    name: str,
    value: float | str,
    comment: str | None = None,
    data_type: ScoreDataType | None = None,
) -> bool:
    """Attach a score to a specific trace (one chat message). Returns True if sent."""
    return _create_score(
        name=name, value=value, trace_id=trace_id, comment=comment, data_type=data_type
    )


def score_session(
    session_id: str,
    name: str,
    value: float | str,
    comment: str | None = None,
    data_type: ScoreDataType | None = None,
) -> bool:
    """Attach a score to a whole Langfuse session (one chat conversation)."""
    return _create_score(
        name=name, value=value, session_id=session_id, comment=comment, data_type=data_type
    )


REVIEW_SCORE_CONFIG_NAME = "review-quality"


def _ensure_review_score_config(client: Any) -> str:
    """Get or create the 1–5 score config reviewers use in the annotation queue."""
    configs = client.api.score_configs.get()
    for config in configs.data:
        if config.name == REVIEW_SCORE_CONFIG_NAME:
            return config.id
    created = client.api.score_configs.create(
        name=REVIEW_SCORE_CONFIG_NAME,
        data_type="NUMERIC",
        min_value=1,
        max_value=5,
        description="Reviewer quality rating for flagged chat answers (1=wrong, 5=perfect)",
    )
    return created.id


def enqueue_for_review(trace_id: str, comment: str | None = None) -> bool:
    """Add a trace to the 'chat-review' Langfuse annotation queue.

    The queue (and its 'review-quality' 1–5 score config) is created on first
    use. Reviewers then annotate the trace in the Langfuse UI (Annotation
    Queues); their scores land on the same trace the frontend flagged. A
    CATEGORICAL 'review-flag' score records why it was flagged.
    """
    if not _initialized:
        return False
    try:
        from langfuse import get_client
        from langfuse.api import AnnotationQueueObjectType

        client = get_client()
        queues = client.api.annotation_queues.list_queues()
        queue = next((q for q in queues.data if q.name == REVIEW_QUEUE_NAME), None)
        if queue is None:
            queue = client.api.annotation_queues.create_queue(
                name=REVIEW_QUEUE_NAME,
                score_config_ids=[_ensure_review_score_config(client)],
            )
        client.api.annotation_queues.create_queue_item(
            queue_id=queue.id,
            object_id=trace_id,
            object_type=AnnotationQueueObjectType.TRACE,
        )
        if comment:
            score_trace(trace_id, "review-flag", "flagged", comment=comment, data_type="CATEGORICAL")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to enqueue trace %s for review: %s", trace_id, exc)
        return False
