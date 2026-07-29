"""Langfuse datasets + experiments (agent task, RAGAS + deterministic scores).

Flow:
1. ``sync_golden_dataset`` pushes the local golden items into the Langfuse
   dataset ``getnet-qa-v1`` — idempotent (item id = golden item id).
   Q&A items (fees / product_howto / general_web) with a curated
   ``expected_answer`` are ACTIVE; support-route, adversarial and locally
   archived items are ARCHIVED in Langfuse (they don't measure Q&A quality).
2. ``run_qa_experiment`` executes the *real* Knowledge Specialist agent
   (graph_search + rag_search + web_search via pydantic-ai) over every active
   dataset item through ``langfuse.run_experiment``, creating a Dataset Run
   with one trace per item. Each item is scored with:
   - RAGAS: faithfulness, answer relevancy, answer correctness (vs the golden
     expected_output) and semantic similarity;
   - deterministic Langfuse scores: tools-match F1 (tools used vs
     expected_tools), expected-facts coverage, and source citation.

RAGAS has no cp314 wheels, so it is lazy-imported: available inside the
runtime image (python 3.12), gracefully reported as unavailable elsewhere.
"""

import asyncio
import logging
from typing import Any

from app.core.config import Settings

from .models import GoldenItem

logger = logging.getLogger(__name__)

DATASET_NAME = "getnet-qa-v1"
EXPERIMENT_NAME = "getnet-qa-agent"

# Categories that measure Q&A quality — everything else is archived in Langfuse.
QA_CATEGORIES = {"fees", "product_howto", "general_web"}


class ExperimentUnavailableError(Exception):
    pass


def _require_langfuse():
    from app.core.tracing import is_tracing_enabled

    if not is_tracing_enabled():
        raise ExperimentUnavailableError("Langfuse tracing is not enabled")
    from langfuse import get_client

    return get_client()


# ---------------------------------------------------------------------------
# Dataset sync
# ---------------------------------------------------------------------------


def _item_metadata(item: GoldenItem) -> dict[str, Any]:
    return {
        "category": item.category,
        "difficulty": item.difficulty,
        "locale": item.locale,
        "gold_source_urls": item.gold_source_urls,
        "expected_tools": item.expected_tools,
        "expected_facts": item.expected_facts,
        "provenance": item.provenance,
        "seed_generation": item.reviewed_by,
        **(item.meta or {}),
    }


def sync_golden_dataset(items: list[GoldenItem]) -> dict[str, Any]:
    """Upsert golden items as a Langfuse dataset. Returns a summary.

    Pass ALL items (including locally archived ones) so that items dropped
    from the active set also get archived in Langfuse.
    """
    client = _require_langfuse()
    try:
        client.api.datasets.get(DATASET_NAME)
    except Exception:  # noqa: BLE001 — not found
        client.create_dataset(
            name=DATASET_NAME,
            description="Getnet Q&A golden dataset (curated from official Getnet pages) "
            "for agent Q&A experiments.",
            metadata={"source": "skywalker golden_items", "namespace": "getnet"},
        )

    synced = 0
    archived = 0
    for item in items:
        is_qa = (
            not item.archived
            and item.category in QA_CATEGORIES
            and bool(item.question.strip())
            and bool((item.expected_answer or "").strip())
        )
        if not is_qa:
            # Support-route items need account tools, adversarial items test
            # guardrails, and archived/incomplete items have no golden answer:
            # none measure Q&A quality, so archive them in Langfuse (upsert by
            # id, so previously-synced copies leave the experiment set).
            try:
                client.create_dataset_item(
                    dataset_name=DATASET_NAME, id=item.id, status="ARCHIVED"
                )
                archived += 1
            except Exception:  # noqa: BLE001 — never synced, nothing to archive
                pass
            continue
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item.id,  # stable id → re-sync updates instead of duplicating
            input={"question": item.question},
            expected_output=item.expected_answer,
            metadata=_item_metadata(item),
        )
        synced += 1
    client.flush()
    return {"dataset": DATASET_NAME, "items_synced": synced, "items_archived": archived}


# ---------------------------------------------------------------------------
# Experiment task — the real Knowledge Specialist agent
# ---------------------------------------------------------------------------


def _build_agent_task(settings: Settings):
    """Task: run the Knowledge Specialist (graph/rag/web tools) per item.

    Thread-local stores/agents are created lazily inside the experiment loop
    (``run_experiment`` manages its own event loop; async clients must not be
    shared across loops). Tool calls are recorded with their FULL results so
    RAGAS can use them as retrieved contexts.
    """
    state: dict[str, Any] = {}

    def _ensure_stores() -> None:
        if "vector_store" in state:
            return
        from app.modules.knowledge.vector_store import QdrantVectorStore

        state["vector_store"] = QdrantVectorStore(settings)
        state["graph_store"] = None
        if settings.graph_enabled:
            from app.modules.knowledge.graph_store import Neo4jGraphStore

            state["graph_store"] = Neo4jGraphStore(settings)

    def _register_recorded_tool(pyd_agent, spec, ctx, calls: list[dict]) -> None:
        params_model = spec.params_model
        handler = spec.handler

        async def tool_fn(params: params_model) -> str:  # type: ignore[valid-type]
            try:
                result_text = await handler(ctx, params)
            except Exception as exc:  # noqa: BLE001 — errors return to the LLM as text
                logger.error("Tool '%s' failed: %s", spec.name, exc, exc_info=True)
                result_text = f"Error in {spec.name}: {exc}"
            calls.append(
                {
                    "tool": spec.name,
                    "args": params.model_dump(exclude_none=True),  # type: ignore[attr-defined]
                    "result": result_text,
                }
            )
            return result_text

        tool_fn.__name__ = spec.name
        pyd_agent.tool_plain(  # type: ignore[call-overload]
            tool_fn, name=spec.name, description=spec.description
        )

    async def task(*, item, **kwargs) -> dict[str, Any]:
        from pydantic_ai import Agent as PydanticAgent
        from pydantic_ai.settings import ModelSettings

        from app.modules.agents.seeds import KNOWLEDGE_INSTRUCTIONS
        from app.modules.tools.definitions import graph_search, rag_search, web_search
        from app.modules.tools.service import ToolRunContext

        _ensure_stores()
        question = (item.input or {}).get("question", "")
        ctx = ToolRunContext(
            settings=settings,
            user_ref="eval-runner",
            session_id=f"eval-{item.id}",
            vector_store=state["vector_store"],
            graph_store=state["graph_store"],
        )
        calls: list[dict] = []
        agent = PydanticAgent(
            model=settings.default_model,
            instructions=KNOWLEDGE_INSTRUCTIONS,
            model_settings=ModelSettings(timeout=settings.llm_request_timeout_seconds),
        )
        for spec in (graph_search.SPEC, rag_search.SPEC, web_search.SPEC):
            _register_recorded_tool(agent, spec, ctx, calls)

        answer = (await agent.run(question)).output
        tools_used = sorted({c["tool"] for c in calls})
        return {
            "answer": answer,
            "contexts": [c["result"] for c in calls],
            "tools_used": tools_used,
            "tool_calls": [{"tool": c["tool"], "args": c["args"]} for c in calls],
        }

    return task


# ---------------------------------------------------------------------------
# Deterministic evaluators (native Langfuse scores)
# ---------------------------------------------------------------------------


def _tools_match_f1(expected: list[str], used: list[str]) -> float:
    """F1 between the expected and actually-used tool sets (1.0 when both empty)."""
    expected_set, used_set = set(expected), set(used)
    if not expected_set and not used_set:
        return 1.0
    if not expected_set or not used_set:
        return 0.0
    tp = len(expected_set & used_set)
    precision = tp / len(used_set)
    recall = tp / len(expected_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


async def _tools_match_evaluator(*, input, output, metadata, **kwargs) -> dict[str, Any]:
    expected = (metadata or {}).get("expected_tools") or []
    used = (output or {}).get("tools_used") or []
    return {
        "name": "tools-match-f1",
        "value": round(_tools_match_f1(expected, used), 4),
        "comment": f"expected={expected} used={used}",
    }


async def _facts_coverage_evaluator(*, output, metadata, **kwargs):
    facts = (metadata or {}).get("expected_facts") or []
    if not facts:
        return []
    answer = ((output or {}).get("answer") or "").casefold()
    hits = [f for f in facts if f.casefold() in answer]
    return {
        "name": "expected-facts-coverage",
        "value": round(len(hits) / len(facts), 4),
        "comment": f"present={hits} missing={[f for f in facts if f not in hits]}",
    }


async def _citation_evaluator(*, output, **kwargs) -> dict[str, Any]:
    answer = (output or {}).get("answer") or ""
    return {
        "name": "cites-source",
        "value": 1.0 if ("http://" in answer or "https://" in answer) else 0.0,
    }


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


async def run_qa_experiment(
    settings: Settings, run_name: str, top_k: int = 5
) -> dict[str, Any]:
    """Run the Knowledge Specialist + evaluators over the Langfuse dataset.

    Runs in a worker thread: ``run_experiment`` manages its own event loop, and
    the task builds thread-local clients (Qdrant/Neo4j/OpenAI) to avoid
    sharing async clients across loops. ``top_k`` is kept for API
    compatibility; the agent's rag_search chooses its own top_k.
    """
    client = _require_langfuse()

    try:
        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerCorrectness,
            AnswerRelevancy,
            Faithfulness,
            SemanticSimilarity,
        )
    except ImportError as exc:
        raise ExperimentUnavailableError(
            "RAGAS is not installed in this runtime (requires python < 3.13). "
            "Run experiments inside the Docker image."
        ) from exc

    dataset = client.get_dataset(DATASET_NAME)
    if not dataset.items:
        raise ExperimentUnavailableError(
            f"Langfuse dataset '{DATASET_NAME}' is empty — sync it first"
        )

    from openai import AsyncOpenAI

    # Bounded per-request timeout + retries: judge calls run 4-concurrent and a
    # single slow request otherwise stalls (default timeout is 600s, and
    # instructor gives up after the first error).
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=120.0, max_retries=5)
    # Default max_tokens=1024 truncates faithfulness NLI verdicts on items
    # with long retrieved contexts (ragas docs recommend 4096+).
    ragas_llm = llm_factory(
        settings.ragas_model, provider="openai", client=openai_client, max_tokens=4096
    )
    ragas_embeddings = embedding_factory(
        "openai", model="text-embedding-3-small", client=openai_client, interface="modern"
    )
    faithfulness = Faithfulness(llm=ragas_llm)
    relevancy = AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings)
    correctness = AnswerCorrectness(llm=ragas_llm, embeddings=ragas_embeddings)
    similarity = SemanticSimilarity(embeddings=ragas_embeddings)

    async def faithfulness_evaluator(*, input, output, **kwargs):
        contexts = (output or {}).get("contexts") or []
        if not contexts:
            return []  # no tool was called — faithfulness is undefined
        try:
            result = await faithfulness.ascore(
                user_input=(input or {}).get("question", ""),
                response=output["answer"],
                retrieved_contexts=contexts,
            )
            return {"name": "ragas-faithfulness", "value": float(result.value)}
        except Exception:
            # run_experiment swallows evaluator errors per item — log them here
            # so failures are diagnosable from the app logs.
            logger.exception(
                "ragas-faithfulness failed for question=%r", (input or {}).get("question")
            )
            raise

    async def relevancy_evaluator(*, input, output, **kwargs):
        try:
            result = await relevancy.ascore(
                user_input=(input or {}).get("question", ""),
                response=output["answer"],
            )
            return {"name": "ragas-answer-relevancy", "value": float(result.value)}
        except Exception:
            logger.exception(
                "ragas-answer-relevancy failed for question=%r", (input or {}).get("question")
            )
            raise

    async def correctness_evaluator(*, input, output, expected_output, **kwargs):
        if not expected_output:
            return []
        try:
            result = await correctness.ascore(
                user_input=(input or {}).get("question", ""),
                response=output["answer"],
                reference=expected_output,
            )
            return {"name": "ragas-answer-correctness", "value": float(result.value)}
        except Exception:
            logger.exception(
                "ragas-answer-correctness failed for question=%r", (input or {}).get("question")
            )
            raise

    async def similarity_evaluator(*, output, expected_output, **kwargs):
        if not expected_output:
            return []
        try:
            result = await similarity.ascore(
                reference=expected_output, response=output["answer"]
            )
            return {"name": "ragas-semantic-similarity", "value": float(result.value)}
        except Exception:
            logger.exception("ragas-semantic-similarity failed")
            raise

    evaluators: list[Any] = [
        faithfulness_evaluator,
        relevancy_evaluator,
        correctness_evaluator,
        similarity_evaluator,
        _tools_match_evaluator,
        _facts_coverage_evaluator,
        _citation_evaluator,
    ]

    def _run() -> Any:
        return client.run_experiment(
            name=EXPERIMENT_NAME,
            run_name=run_name,
            description=(
                "Knowledge Specialist agent (graph/rag/web tools) over the golden "
                "Q&A dataset, scored with RAGAS + deterministic tool/fact checks"
            ),
            data=dataset.items,
            task=_build_agent_task(settings),
            evaluators=evaluators,
            max_concurrency=4,
            metadata={
                "agent": "knowledge-specialist",
                "model": settings.default_model,
                "namespace": settings.default_namespace,
            },
        )

    experiment = await asyncio.to_thread(_run)
    client.flush()

    # Aggregate item-level evaluations for our local EvalRun record
    totals: dict[str, list[float]] = {}
    for item_result in experiment.item_results:
        for evaluation in item_result.evaluations:
            if isinstance(evaluation.value, int | float):
                totals.setdefault(evaluation.name, []).append(float(evaluation.value))
    aggregated = {
        name: round(sum(values) / len(values), 4) for name, values in totals.items() if values
    }
    aggregated["items_evaluated"] = len(experiment.item_results)
    return {
        "run_name": run_name,
        "dataset": DATASET_NAME,
        "metrics": aggregated,
        "dataset_run_id": getattr(experiment, "dataset_run_id", None),
    }


# Backwards-compatible alias (older callers/service code)
run_ragas_experiment = run_qa_experiment
