"""Evaluation business logic — golden dataset CRUD, eval runs, feedback promotion."""

import logging
from datetime import UTC, datetime

from app.core.config import Settings
from app.modules.chat.repository import ChatRepository

from . import metrics as m
from .enums import EvalLayer, EvalRunStatus, Provenance
from .models import EvalResult, EvalRun, GoldenItem
from .repository import EvaluationRepository
from .schemas import (
    EvalRunCreate,
    EvalRunRead,
    GoldenItemCreate,
    GoldenItemRead,
    GoldenItemUpdate,
    PromoteFromMessageCreate,
)

logger = logging.getLogger(__name__)


class EvaluationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class EvaluationService:
    def __init__(
        self,
        repository: EvaluationRepository,
        settings: Settings,
        vector_store=None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.vector_store = vector_store

    # ------------------------------------------------------------------
    # Golden dataset
    # ------------------------------------------------------------------

    async def create_item(self, payload: GoldenItemCreate) -> GoldenItemRead:
        item = GoldenItem(**payload.model_dump())
        item = await self.repository.create_item(item)
        return GoldenItemRead.model_validate(item)

    async def update_item(self, item_id: str, payload: GoldenItemUpdate) -> GoldenItemRead:
        item = await self.repository.get_item(item_id)
        if item is None:
            raise EvaluationError("Golden item not found", 404)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        item = await self.repository.save_item(item)
        return GoldenItemRead.model_validate(item)

    async def list_items(self, include_archived: bool = False) -> list[GoldenItemRead]:
        items = await self.repository.list_items(include_archived)
        return [GoldenItemRead.model_validate(i) for i in items]

    async def promote_from_message(
        self, payload: PromoteFromMessageCreate, chat_repository: ChatRepository
    ) -> GoldenItemRead:
        """Turn a chat exchange (typically a thumbs-down) into a golden item draft."""
        message = await chat_repository.get_message(payload.message_id)
        if message is None:
            raise EvaluationError("Message not found", 404)

        # The question is the user message immediately before this assistant message
        messages = await chat_repository.list_messages(message.session_id)
        question = None
        for i, msg in enumerate(messages):
            if msg.id == message.id:
                for prev in reversed(messages[:i]):
                    if prev.role == "user":
                        question = prev.content
                        break
                break
        if question is None:
            raise EvaluationError("Could not locate the user question for this message", 400)

        item = GoldenItem(
            question=question,
            category=payload.category,
            expected_answer=payload.expected_answer or message.content,
            gold_source_urls=payload.gold_source_urls,
            provenance=Provenance.PRODUCTION_TRACE,
            source_message_id=message.id,
        )
        item = await self.repository.create_item(item)
        return GoldenItemRead.model_validate(item)

    # ------------------------------------------------------------------
    # Eval runs
    # ------------------------------------------------------------------

    async def sync_langfuse_dataset(self) -> dict:
        """Push the golden dataset into Langfuse (dataset 'getnet-qa-v1')."""
        from .langfuse_experiments import ExperimentUnavailableError, sync_golden_dataset

        # Include archived items so removing one from the active set also
        # archives its previously-synced copy in Langfuse.
        items = await self.repository.list_items(include_archived=True)
        try:
            return sync_golden_dataset(items)
        except ExperimentUnavailableError as exc:
            raise EvaluationError(str(exc), 503) from exc

    async def start_run(self, payload: EvalRunCreate) -> EvalRunRead:
        if self.vector_store is None:
            raise EvaluationError("Vector store not configured", 503)

        run = EvalRun(
            name=payload.name,
            layer=payload.layer,
            status=EvalRunStatus.RUNNING,
            config={
                "top_k": payload.top_k,
                "namespace": payload.namespace or self.settings.default_namespace,
                "embedding_model": self.settings.embedding_model,
                "collection": self.settings.qdrant_collection,
            },
        )
        run = await self.repository.create_run(run)

        try:
            if payload.layer == EvalLayer.FULL:
                metrics = await self._run_full_layer(run, payload)
            else:
                metrics = await self._run_retrieval_layer(run, payload)
            run.metrics = metrics
            run.status = EvalRunStatus.COMPLETED
        except EvaluationError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Eval run failed: %s", exc, exc_info=True)
            run.status = EvalRunStatus.FAILED
            run.error = str(exc)
        run.completed_at = datetime.now(UTC)
        run = await self.repository.save_run(run)
        return EvalRunRead.model_validate(run)

    async def _run_full_layer(self, run: EvalRun, payload: EvalRunCreate) -> dict:
        """RAG end-to-end over the Langfuse dataset, scored with RAGAS.

        Creates a Langfuse Dataset Run (one trace per item + scores); the local
        EvalRun row stores the aggregates for the frontend comparison table.
        """
        from .langfuse_experiments import ExperimentUnavailableError, run_qa_experiment

        try:
            result = await run_qa_experiment(
                self.settings, run_name=payload.name, top_k=payload.top_k
            )
        except ExperimentUnavailableError as exc:
            raise EvaluationError(str(exc), 503) from exc

        run.config = {**run.config, "langfuse_dataset": result["dataset"]}
        return result["metrics"]

    async def _run_retrieval_layer(self, run: EvalRun, payload: EvalRunCreate) -> dict:
        items = [
            i for i in await self.repository.list_items() if i.gold_source_urls
        ]
        if not items:
            raise EvaluationError(
                "No golden items with gold_source_urls — retrieval eval needs them", 400
            )

        namespace = payload.namespace or self.settings.default_namespace
        per_item_metrics: list[dict[str, float]] = []

        for item in items:
            results = await self.vector_store.query(
                query_text=item.question, top_k=payload.top_k, namespace=namespace
            )
            retrieved_urls = [r["metadata"].get("source_url", "") for r in results]
            item_metrics = {
                f"recall@{payload.top_k}": m.recall_at_k(
                    item.gold_source_urls, retrieved_urls, payload.top_k
                ),
                f"hit@{payload.top_k}": m.hit_at_k(
                    item.gold_source_urls, retrieved_urls, payload.top_k
                ),
                "mrr": m.mrr(item.gold_source_urls, retrieved_urls),
            }
            per_item_metrics.append(item_metrics)
            await self.repository.add_result(
                EvalResult(
                    run_id=run.id,
                    item_id=item.id,
                    metrics=item_metrics,
                    retrieved_urls=retrieved_urls,
                )
            )

        aggregated = m.aggregate(per_item_metrics)
        aggregated["items_evaluated"] = len(items)
        return aggregated

    async def list_runs(self) -> list[EvalRunRead]:
        return [EvalRunRead.model_validate(r) for r in await self.repository.list_runs()]

    async def get_run(self, run_id: str) -> EvalRunRead:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise EvaluationError("Run not found", 404)
        return EvalRunRead.model_validate(run)
