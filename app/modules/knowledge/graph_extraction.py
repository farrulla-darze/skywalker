"""LLM fact extraction → Neo4j knowledge graph.

Design (see REVIEW_AND_ROADMAP.md §5): instead of open-ended entity extraction
(GraphRAG-style community detection is overkill and underperforms on factoid
lookups over a small product corpus), we extract into a FIXED domain schema —
Product / Fee / Feature — with pydantic-ai structured output. Every fact
carries the source URL it was extracted from, so graph answers are citable.

The extraction reads the already-ingested chunks from Qdrant (grouped back
into per-URL documents), so no re-scraping is needed.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent

from app.core.config import Settings

from .graph_store import Neo4jGraphStore
from .vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

MAX_DOC_CHARS = 24_000

_EXTRACTION_INSTRUCTIONS = """\
You extract STRUCTURED product facts from a payments-company web page (Getnet Brasil).

Rules:
- Extract ONLY facts explicitly stated in the text. Never infer or invent rates.
- `slug`: kebab-case product identifier (e.g. "get-smart", "get-classica", "get-mini",
  "pix", "crediario", "link-de-pagamento", "antecipacao", "conta-digital").
- Fees: one entry per (modality, installments, plan) combination found. `rate_pct` is the
  numeric percentage (e.g. "3,79%" -> 3.79). Use `installments` only when the fee is tied
  to a specific installment count; use `plan` only when tied to a named plan/tier.
  Monthly rental values in R$ are NOT percentage fees — put those in features instead
  (e.g. name="aluguel", description="R$ 79,90/mês, zero acima de R$ 999 em vendas").
- Features: short, factual capabilities/conditions (max installments, settlement time,
  connectivity, free-machine conditions, etc). Keep descriptions under 200 chars.
- If the page has no extractable product facts, return an empty products list.
"""


class FeeFact(BaseModel):
    modality: str = Field(description="e.g. 'débito', 'crédito à vista', 'crédito parcelado', 'pix'")
    rate_pct: float = Field(description="Percentage as a number, e.g. 3.79")
    installments: int | None = Field(default=None, description="Installment count if fee-specific")
    plan: str | None = Field(default=None, description="Plan/tier name if fee is plan-specific")


class FeatureFact(BaseModel):
    name: str = Field(description="Short feature/condition name")
    description: str = Field(description="Factual description, max ~200 chars")


class ProductFacts(BaseModel):
    name: str = Field(description="Product display name, e.g. 'Get Smart'")
    slug: str = Field(description="kebab-case identifier, e.g. 'get-smart'")
    fees: list[FeeFact] = Field(default_factory=list)
    features: list[FeatureFact] = Field(default_factory=list)


class ExtractionOutput(BaseModel):
    products: list[ProductFacts] = Field(default_factory=list)


@dataclass
class ExtractionSummary:
    namespace: str
    urls_processed: int = 0
    urls_failed: int = 0
    products_upserted: int = 0
    fees_upserted: int = 0
    features_upserted: int = 0
    errors: list[str] = field(default_factory=list)


class GraphExtractionService:
    """Reconstructs per-URL documents from Qdrant chunks and extracts typed facts."""

    def __init__(
        self,
        settings: Settings,
        vector_store: QdrantVectorStore,
        graph_store: Neo4jGraphStore,
    ) -> None:
        self.settings = settings
        self.vector_store = vector_store
        self.graph_store = graph_store

    def _extraction_agent(self) -> "PydanticAgent[None, ExtractionOutput]":
        return PydanticAgent(
            model=self.settings.default_model,
            instructions=_EXTRACTION_INSTRUCTIONS,
            output_type=ExtractionOutput,
        )

    async def extract_namespace(self, namespace: str | None = None) -> ExtractionSummary:
        namespace = namespace or self.settings.default_namespace
        summary = ExtractionSummary(namespace=namespace)

        chunks = await self.vector_store.list_chunks(namespace)
        if not chunks:
            summary.errors.append(f"No chunks found in namespace '{namespace}' — ingest first")
            return summary

        # Rebuild one document per source URL, in chunk order, without overlap
        # duplication (use `body` when present, fall back to chunk_text).
        by_url: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for payload in chunks:
            url = payload.get("source_url", "")
            text = payload.get("body") or payload.get("chunk_text", "")
            if url and text:
                by_url[url].append((payload.get("chunk_index", 0), text))

        await self.graph_store.ensure_schema()

        for url, parts in sorted(by_url.items()):
            document = "\n\n".join(text for _, text in sorted(parts))[:MAX_DOC_CHARS]
            try:
                result = await self._extraction_agent().run(
                    f"Source URL: {url}\n\nPage content:\n{document}"
                )
                output = result.output
            except Exception as exc:  # noqa: BLE001 — per-URL isolation
                logger.error("Fact extraction failed for %s: %s", url, exc)
                summary.urls_failed += 1
                summary.errors.append(f"{url}: {exc}")
                continue

            for product in output.products:
                await self.graph_store.upsert_product(product.name, product.slug, url)
                summary.products_upserted += 1
                for fee in product.fees:
                    await self.graph_store.upsert_fee(
                        product_slug=product.slug,
                        modality=fee.modality,
                        rate_pct=fee.rate_pct,
                        source_url=url,
                        installments=fee.installments,
                        plan=fee.plan,
                    )
                    summary.fees_upserted += 1
                for feature in product.features:
                    await self.graph_store.upsert_feature(
                        product_slug=product.slug,
                        name=feature.name,
                        description=feature.description,
                        source_url=url,
                    )
                    summary.features_upserted += 1

            summary.urls_processed += 1
            logger.info(
                "Extracted facts from %s: %d product(s)", url, len(output.products)
            )

        return summary
