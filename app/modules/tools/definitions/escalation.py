"""consult_human — the single human-in-the-loop channel.

The agent stays in charge of the conversation: it posts ONE precise question
(with gathered context) to the support staff on Telegram, blocks until the
reply (or timeout), and uses the answer to respond to the customer. Follow-up
rounds are additional calls. There is no full-handoff tool: even an explicit
"quero falar com um humano" is served by consulting the specialist and
relaying their words.
"""

import logging

from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec

logger = logging.getLogger(__name__)


class ConsultHumanParams(BaseModel):
    question: str = Field(
        description=(
            "ONE precise, self-contained question for the human specialist "
            "(e.g. 'May I apply the 10% MDR discount to this Pro-tier merchant "
            "with R$80k/month volume?')"
        )
    )
    context: str = Field(
        description=(
            "Concise context the human needs to decide: who the customer is, what "
            "the tools showed (account status, tier, relevant numbers), and what "
            "decision or information is needed. No filler."
        )
    )


async def _consult_handler(ctx: ToolRunContext, params: ConsultHumanParams) -> str:
    if ctx.consult is None:
        return (
            "Human consultation channel is not configured. Do not invent an answer: "
            "tell the customer a specialist needs to review this and will follow up."
        )
    try:
        return await ctx.consult(
            params.question, params.context, ctx.current_agent_label or "Agente"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Human consultation failed: %s", exc, exc_info=True)
        return f"Human consultation failed: {exc}"


CONSULT_SPEC = ToolSpec(
    name="consult_human",
    label="Consult Human Specialist",
    description=(
        "Ask the human support staff (on Telegram) ONE precise question and WAIT for "
        "their reply, while you stay in charge of the conversation. Use when an action "
        "requires human permission (editing customer data, verifying extra-private "
        "information, changing product tiers/plans, applying discounts or fee "
        "exceptions, releasing money held by compliance/fraud review) or when you are "
        "not confident about a complex, high-stakes answer — including when the "
        "customer explicitly asks for a human. Gather context with your other tools "
        "FIRST, then ask. If the reply asks for more context or is insufficient, call "
        "again as a follow-up. Use the final answer to respond to the customer in your "
        "own words."
    ),
    category=ToolCategory.ACTION,
    params_model=ConsultHumanParams,
    handler=_consult_handler,
)
