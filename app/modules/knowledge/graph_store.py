"""Neo4j knowledge graph store.

Domain-schema property graph (see REVIEW_AND_ROADMAP.md §5):

    (:Product {name, slug, url})
       -[:HAS_FEE]->     (:Fee {modality, installments, rate_pct, plan, source_url})
       -[:HAS_FEATURE]-> (:Feature {name, description, source_url})

Facts are typed and always carry a source_url — structured questions
("what are the debit fees?") are answered from facts, not prose chunks.
"""

import logging
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import Settings

logger = logging.getLogger(__name__)


class Neo4jGraphStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._driver: AsyncDriver | None = None

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
        return self._driver

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def ensure_schema(self) -> None:
        async with self.driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT product_slug IF NOT EXISTS "
                "FOR (p:Product) REQUIRE p.slug IS UNIQUE"
            )

    async def upsert_product(self, name: str, slug: str, url: str) -> None:
        async with self.driver.session() as session:
            await session.run(
                "MERGE (p:Product {slug: $slug}) SET p.name = $name, p.url = $url",
                slug=slug, name=name, url=url,
            )

    async def upsert_fee(
        self,
        product_slug: str,
        modality: str,
        rate_pct: float,
        source_url: str,
        installments: int | None = None,
        plan: str | None = None,
    ) -> None:
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (p:Product {slug: $slug})
                MERGE (p)-[:HAS_FEE]->(f:Fee {
                    modality: $modality,
                    installments: coalesce($installments, 0),
                    plan: coalesce($plan, 'default')
                })
                SET f.rate_pct = $rate_pct, f.source_url = $source_url
                """,
                slug=product_slug, modality=modality, installments=installments,
                plan=plan, rate_pct=rate_pct, source_url=source_url,
            )

    async def upsert_feature(
        self, product_slug: str, name: str, description: str, source_url: str
    ) -> None:
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (p:Product {slug: $slug})
                MERGE (p)-[:HAS_FEATURE]->(f:Feature {name: $name})
                SET f.description = $description, f.source_url = $source_url
                """,
                slug=product_slug, name=name, description=description, source_url=source_url,
            )

    async def get_product_facts(self, product_query: str) -> list[dict[str, Any]]:
        """Fetch fees and features for products matching *product_query* (fuzzy contains)."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (p:Product)
                WHERE toLower(p.name) CONTAINS toLower($q) OR toLower(p.slug) CONTAINS toLower($q)
                OPTIONAL MATCH (p)-[:HAS_FEE]->(fee:Fee)
                OPTIONAL MATCH (p)-[:HAS_FEATURE]->(feat:Feature)
                RETURN p.name AS product, p.url AS url,
                       collect(DISTINCT {modality: fee.modality, installments: fee.installments,
                                         plan: fee.plan, rate_pct: fee.rate_pct,
                                         source_url: fee.source_url}) AS fees,
                       collect(DISTINCT {name: feat.name, description: feat.description,
                                         source_url: feat.source_url}) AS features
                """,
                q=product_query,
            )
            records = [record.data() async for record in result]

        # Drop empty optional-match placeholders
        for record in records:
            record["fees"] = [f for f in record["fees"] if f.get("modality")]
            record["features"] = [f for f in record["features"] if f.get("name")]
        return records

    async def list_products(self) -> list[dict[str, Any]]:
        async with self.driver.session() as session:
            result = await session.run(
                "MATCH (p:Product) RETURN p.name AS name, p.slug AS slug, p.url AS url"
            )
            return [record.data() async for record in result]
