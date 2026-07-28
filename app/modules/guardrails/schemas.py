"""Guardrails schemas — the LLM is forced into this structure via output_type
(no fragile string-prefix parsing)."""

from pydantic import BaseModel, Field

from .enums import GuardrailCategory, GuardrailVerdictType


class GuardrailVerdict(BaseModel):
    verdict: GuardrailVerdictType = Field(description="allow or block")
    category: GuardrailCategory = Field(description="What kind of issue was detected, if any")
    reason: str = Field(description="One-sentence justification")
    safe_response: str | None = Field(
        default=None,
        description="If blocking, a polite response to send to the user instead",
    )
