"""Request/response schemas for the chat API."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /chat request body."""
    user_id: str = Field(
        ...,
        alias="userId",
        description="Unique user identifier. Used to find or create a session.",
        min_length=1,
    )
    question: str = Field(
        ...,
        description="The user's question or message.",
        min_length=1,
    )
    session_id: Optional[str] = Field(
        None,
        alias="sessionId",
        description="Optional session ID to continue an existing conversation. If not provided, a new session is created.",
    )
    session_id: Optional[str] = Field(
        None,
        alias="sessionId",
        description="Optional session ID to append to existing conversation. If not provided or invalid, creates a new session.",
    )


class ChatResponse(BaseModel):
    """POST /chat response body."""
    session_id: str = Field(
        ...,
        alias="sessionId",
        description="Session identifier (reuse across messages for continuity).",
    )
    response: str = Field(
        ...,
        description="Agent's answer.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Token counts and other run metadata.",
    )
