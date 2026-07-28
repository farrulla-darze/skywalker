"""graph_search — structured facts (fees, features) from the Neo4j knowledge graph.

For questions about fees/rates/pricing this is preferred over rag_search:
answers come from typed facts with a source URL instead of prose chunks.
"""

import logging

from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec

logger = logging.getLogger(__name__)


class GraphSearchParams(BaseModel):
    product: str = Field(
        description="Product name or slug to look up, e.g. 'maquininha', 'pix', 'tap to pay'"
    )


async def _handler(ctx: ToolRunContext, params: GraphSearchParams) -> str:
    if ctx.graph_store is None or not ctx.settings.graph_enabled:
        return (
            "Knowledge graph is not enabled. Use rag_search for this question instead."
        )

    try:
        records = await ctx.graph_store.get_product_facts(params.product)
    except Exception as exc:  # noqa: BLE001
        logger.error("graph_search failed: %s", exc, exc_info=True)
        return f"Knowledge graph query failed: {exc}. Fall back to rag_search."

    records = [r for r in records if r.get("fees") or r.get("features")]
    if not records:
        return (
            f"No structured facts found for '{params.product}'. "
            "Fall back to rag_search for this question."
        )

    lines = []
    for record in records:
        lines.append(f"## {record['product']}")
        if record.get("url"):
            lines.append(f"Source: {record['url']}")
        if record["fees"]:
            lines.append("Fees:")
            for fee in record["fees"]:
                installments = (
                    f" ({fee['installments']}x)" if fee.get("installments") else ""
                )
                plan = f" [plan: {fee['plan']}]" if fee.get("plan", "default") != "default" else ""
                lines.append(
                    f"- {fee['modality']}{installments}{plan}: {fee['rate_pct']}% "
                    f"(source: {fee['source_url']})"
                )
        if record["features"]:
            lines.append("Features:")
            for feat in record["features"]:
                lines.append(f"- {feat['name']}: {feat['description']}")
        lines.append("")
    return "\n".join(lines)


SPEC = ToolSpec(
    name="graph_search",
    label="Knowledge Graph Search",
    description=(
        "Look up STRUCTURED facts about a Getnet product: fees/rates per "
        "modality and plan, and features. Prefer this over rag_search for questions "
        "about fees, rates, costs or pricing — facts are typed and carry source URLs."
    ),
    category=ToolCategory.KNOWLEDGE,
    params_model=GraphSearchParams,
    handler=_handler,
)
