"""Langfuse datasets + experiments with RAGAS evaluators.

Flow:
1. ``sync_golden_dataset`` pushes the local golden items into a Langfuse
   dataset (``getnet-qa-v1``) — idempotent (item id = golden item id).
2. ``run_ragas_experiment`` executes a RAG task (retrieve from Qdrant +
   generate) over every dataset item via ``langfuse.run_experiment``, which
   creates a Dataset Run in Langfuse with one trace per item and attaches
   the RAGAS scores (faithfulness, answer relevancy) to each.

RAGAS has no cp314 wheels, so it is lazy-imported: available inside the
runtime image (python 3.12), gracefully reported as unavailable elsewhere.
"""

import asyncio
import logging
from typing import Any

from app.core.config import Settings
from app.modules.knowledge.vector_store import QdrantVectorStore

from .models import GoldenItem

logger = logging.getLogger(__name__)

DATASET_NAME = "getnet-qa-v1"
RAG_ANSWER_INSTRUCTIONS = (
    "You are a Getnet support assistant. Answer the question using ONLY the "
    "provided context chunks. Cite the source URL of the chunks you used. "
    "If the context does not contain the answer, say so explicitly."
)


class ExperimentUnavailableError(Exception):
    pass


def _require_langfuse():
    from app.core.tracing import is_tracing_enabled

    if not is_tracing_enabled():
        raise ExperimentUnavailableError("Langfuse tracing is not enabled")
    from langfuse import get_client

    return get_client()


def sync_golden_dataset(items: list[GoldenItem]) -> dict[str, Any]:
    """Upsert golden items as a Langfuse dataset. Returns a summary."""
    client = _require_langfuse()
    try:
        client.api.datasets.get(DATASET_NAME)
    except Exception:  # noqa: BLE001 — not found
        client.create_dataset(
            name=DATASET_NAME,
            description="Getnet Q&A golden dataset (challenge scenarios + curated items) "
            "for RAG experiments.",
            metadata={"source": "skywalker golden_items", "namespace": "getnet"},
        )

    synced = 0
    archived = 0
    for item in items:
        # adversarial → tests guardrails; general_web → tests routing/web_search.
        # Neither measures RAG quality: archive them in the Langfuse dataset
        # (upsert by id) so previously-synced copies leave the experiment set.
        if item.category in ("adversarial", "general_web"):
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
            expected_output=item.expected_answer or None,
            metadata={
                "category": item.category,
                "locale": item.locale,
                "gold_source_urls": item.gold_source_urls,
                "expected_tools": item.expected_tools,
            },
        )
        synced += 1
    client.flush()
    return {"dataset": DATASET_NAME, "items_synced": synced, "items_archived": archived}


async def run_ragas_experiment(
    settings: Settings, run_name: str, top_k: int = 5
) -> dict[str, Any]:
    """Run the RAG task + RAGAS evaluators over the Langfuse dataset.

    Runs in a worker thread: ``run_experiment`` manages its own event loop, and
    the task builds thread-local clients (Qdrant/OpenAI) to avoid sharing
    async clients across loops.
    """
    client = _require_langfuse()

    try:
        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import AnswerRelevancy, Faithfulness
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

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    ragas_llm = llm_factory(settings.ragas_model, provider="openai", client=openai_client)
    ragas_embeddings = embedding_factory(
        "openai", model="text-embedding-3-small", client=openai_client, interface="modern"
    )
    faithfulness = Faithfulness(llm=ragas_llm)
    relevancy = AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings)

    def _build_task():
        # Thread-local stores/agents, created lazily inside the experiment loop
        state: dict[str, Any] = {}

        async def task(*, item, **kwargs) -> dict[str, Any]:
            from pydantic_ai import Agent as PydanticAgent

            if "vector_store" not in state:
                state["vector_store"] = QdrantVectorStore(settings)
                state["agent"] = PydanticAgent(
                    model=settings.default_model, instructions=RAG_ANSWER_INSTRUCTIONS
                )
            question = (item.input or {}).get("question", "")
            results = await state["vector_store"].query(
                query_text=question, top_k=top_k, namespace=settings.default_namespace
            )
            contexts = [
                r["metadata"].get("chunk_text", "")
                for r in results
                if r["metadata"].get("chunk_text")
            ]
            sources = [r["metadata"].get("source_url", "") for r in results]
            prompt = f"Question: {question}\n\nContext chunks:\n" + "\n\n---\n\n".join(contexts)
            answer = (await state["agent"].run(prompt)).output
            return {"answer": answer, "contexts": contexts, "sources": sources}

        return task

    async def faithfulness_evaluator(*, input, output, **kwargs) -> dict[str, Any]:
        try:
            result = await faithfulness.ascore(
                user_input=(input or {}).get("question", ""),
                response=output["answer"],
                retrieved_contexts=output["contexts"],
            )
            return {"name": "ragas-faithfulness", "value": float(result.value)}
        except Exception:
            # run_experiment swallows evaluator errors per item — log them here
            # so failures are diagnosable from the app logs.
            logger.exception("ragas-faithfulness failed for question=%r", (input or {}).get("question"))
            raise

    async def relevancy_evaluator(*, input, output, **kwargs) -> dict[str, Any]:
        try:
            result = await relevancy.ascore(
                user_input=(input or {}).get("question", ""),
                response=output["answer"],
            )
            return {"name": "ragas-answer-relevancy", "value": float(result.value)}
        except Exception:
            logger.exception("ragas-answer-relevancy failed for question=%r", (input or {}).get("question"))
            raise

    def _run() -> Any:
        return client.run_experiment(
            name="getnet-rag",
            run_name=run_name,
            description="RAG over getnet namespace scored with RAGAS",
            data=dataset.items,
            task=_build_task(),
            evaluators=[faithfulness_evaluator, relevancy_evaluator],
            max_concurrency=4,
            metadata={"top_k": str(top_k), "namespace": settings.default_namespace},
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
