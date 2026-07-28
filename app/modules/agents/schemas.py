"""Agents Pydantic schemas."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import AgentKind

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,118}$")


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=120)
    description: str = ""
    instructions: str = Field(min_length=1)
    model: str | None = None
    kind: AgentKind = AgentKind.SPECIALIST
    expose_as_tool: bool = True
    enabled: bool = True
    tools: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase alphanumeric with '-' or '_' (e.g. 'customer-support')"
            )
        return v


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    instructions: str | None = Field(default=None, min_length=1)
    model: str | None = None
    kind: AgentKind | None = None
    expose_as_tool: bool | None = None
    enabled: bool | None = None
    tools: list[str] | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str
    instructions: str
    model: str | None
    kind: AgentKind
    expose_as_tool: bool
    enabled: bool
    tools: list[str]
    is_system: bool
    created_at: datetime
    updated_at: datetime
