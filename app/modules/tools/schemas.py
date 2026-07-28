"""Tools Pydantic schemas."""

from typing import Any

from pydantic import BaseModel

from .enums import ToolCategory


class ToolInfoRead(BaseModel):
    """Tool catalog entry, as shown in the frontend integrations/agent-builder UI."""

    name: str
    label: str
    description: str
    category: ToolCategory
    parameters_json_schema: dict[str, Any]


class StepRecord(BaseModel):
    """One agent step (tool call) — persisted with the message, rendered in the UI."""

    tool: str
    args: dict[str, Any] | None = None
    result_preview: str = ""
    duration_ms: int = 0
    nested_steps: list["StepRecord"] | None = None


StepRecord.model_rebuild()
