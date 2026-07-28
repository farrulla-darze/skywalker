"""Chat Pydantic schemas."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.modules.tools.schemas import StepRecord

from .enums import ChatChannel, FeedbackRating, HandoffState, MessageRole


class ChatSessionCreate(BaseModel):
    agent_id: str | None = None
    title: str | None = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    channel: ChatChannel
    agent_id: str | None
    handoff_state: HandoffState
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: FeedbackRating
    comment: str | None


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: MessageRole
    content: str
    steps: list[StepRecord] | None
    usage: dict | None
    trace_id: str | None = None
    created_at: datetime
    feedback: FeedbackRead | None = None


class MessageFeedbackCreate(BaseModel):
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=2000)


class SessionScoreCreate(BaseModel):
    """1–5 rating for a whole conversation (pushed to Langfuse as session score)."""

    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewFlagCreate(BaseModel):
    """Flag a message for human review (Langfuse annotation queue)."""

    comment: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Legacy challenge endpoint (POST /chat) — accepts BOTH payload shapes:
# the challenge spec {"message", "user_id"} and the v1 API {"question", "userId"}.
# ---------------------------------------------------------------------------


class LegacyChatRequest(BaseModel):
    message: str = Field(validation_alias=AliasChoices("message", "question"))
    user_id: str = Field(validation_alias=AliasChoices("user_id", "userId"))
    session_id: str | None = Field(
        default=None, validation_alias=AliasChoices("session_id", "sessionId")
    )


class LegacyChatResponse(BaseModel):
    sessionId: str
    response: str
    metadata: dict
