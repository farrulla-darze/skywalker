"""YAML-based agent configuration schema."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from typing import Any, List, Optional


class TriggerConfig(BaseModel):
    """How the agent is triggered."""
    type: Literal["sub_agent"] = "sub_agent"


class AgentToolsConfig(BaseModel):
    """Tools configuration for a YAML agent."""
    include: List[str] = Field(default_factory=list)


class YAMLAgentConfig(BaseModel):
    """Configuration for a YAML-defined agent.

    Each .yml file under .skywalker/agents/ is validated against this schema.
    """
    name: str = Field(..., description="Unique agent name (used as tool name)")
    description: str = Field(..., description="Description shown to the orchestrator LLM")
    prompt: str = Field(..., description="System prompt for the sub-agent")
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    tools: AgentToolsConfig = Field(default_factory=AgentToolsConfig)
    model: Optional[str] = Field(default=None, description="Model override (provider:model)")



# ========= Tool Call Dependencies =========


class ToolsetDependencies(BaseModel):
    """Metadata for a toolset's runtime dependencies."""
    id: str
    metadata: Any


@dataclass
class BasicDependencies:
    """Core dependencies passed to every agent execution."""
    user_id: str
    session_id: str
    message: Optional[str] = None
    toolset_dependencies: List[ToolsetDependencies] = field(default_factory=list)


# ========= Agent Executor Responses =========


class AgentExecutorResponse(BaseModel):
    """Response from AgentExecutor.get_response()."""
    success: bool
    error: Optional[str] = None
    session_id: str
    response: str
    tool_calls: List[str]


# ========= Guardrail Responses =========


class AgentGuardrailResponse(BaseModel):
    """Response from guardrail validation.

    When approved=False, the response contains a pre-composed message
    to send to the user instead of calling the LLM.
    """
    approved: bool = Field(..., description="Whether the input passed guardrails")
    reason: str = Field(..., description="Reason for approval/rejection")
    response: Optional[str] = Field(None, description="Pre-composed response if rejected")
    