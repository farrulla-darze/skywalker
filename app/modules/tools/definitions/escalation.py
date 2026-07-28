"""escalate_to_human — hand the conversation off to a human support agent."""

import logging

from pydantic import BaseModel, Field

from ..enums import ToolCategory
from ..service import ToolRunContext, ToolSpec

logger = logging.getLogger(__name__)


class EscalateParams(BaseModel):
    reason: str = Field(description="Why this conversation needs a human (short)")
    summary: str = Field(
        description="Concise summary of the customer's problem and what was already tried"
    )


async def _handler(ctx: ToolRunContext, params: EscalateParams) -> str:
    if ctx.escalate is None:
        return (
            "Escalation channel is not configured. Tell the customer a human will "
            "follow up and suggest contacting official support channels."
        )
    try:
        return await ctx.escalate(params.reason, params.summary)
    except Exception as exc:  # noqa: BLE001
        logger.error("Escalation failed: %s", exc, exc_info=True)
        return f"Escalation failed: {exc}"


SPEC = ToolSpec(
    name="escalate_to_human",
    label="Escalate to Human",
    description=(
        "Escalate this conversation to a human support agent. Use when the customer "
        "explicitly asks for a human, when the issue involves account blocks/money that "
        "you cannot resolve, or when you are not confident in the answer. After calling "
        "this, tell the customer a human agent will take over."
    ),
    category=ToolCategory.ACTION,
    params_model=EscalateParams,
    handler=_handler,
)


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
            "tell the customer a specialist needs to review this and offer escalation."
        )
    try:
        return await ctx.consult(params.question, params.context)
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
        "exceptions) or when you are not confident about a complex, high-stakes "
        "answer. Gather context with your other tools FIRST, then ask. If the reply "
        "asks for more context or is insufficient, call again as a follow-up. Use the "
        "final answer to respond to the customer in your own words."
    ),
    category=ToolCategory.ACTION,
    params_model=ConsultHumanParams,
    handler=_consult_handler,
)
