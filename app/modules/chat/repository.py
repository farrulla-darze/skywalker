"""Chat persistence layer."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatMessage, ChatSession, MessageFeedback


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Sessions ---------------------------------------------------------

    async def create_session(self, chat_session: ChatSession) -> ChatSession:
        self.session.add(chat_session)
        await self.session.commit()
        await self.session.refresh(chat_session)
        return chat_session

    async def get_session(self, session_id: str) -> ChatSession | None:
        return await self.session.get(ChatSession, session_id)

    async def list_sessions_for_user(self, user_id: str) -> list[ChatSession]:
        result = await self.session.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
        )
        return list(result.scalars().all())

    async def find_session_by_external_ref(
        self, external_ref: str, channel: str
    ) -> ChatSession | None:
        result = await self.session.execute(
            select(ChatSession)
            .where(ChatSession.external_ref == external_ref, ChatSession.channel == channel)
            .order_by(ChatSession.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def save_session(self, chat_session: ChatSession) -> ChatSession:
        self.session.add(chat_session)
        await self.session.commit()
        await self.session.refresh(chat_session)
        return chat_session

    # --- Messages ---------------------------------------------------------

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def get_message(self, message_id: str) -> ChatMessage | None:
        return await self.session.get(ChatMessage, message_id)

    async def list_messages(self, session_id: str) -> list[ChatMessage]:
        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())

    # --- Feedback ---------------------------------------------------------

    async def upsert_feedback(self, feedback: MessageFeedback) -> MessageFeedback:
        existing = await self.session.execute(
            select(MessageFeedback).where(MessageFeedback.message_id == feedback.message_id)
        )
        current = existing.scalar_one_or_none()
        if current:
            current.rating = feedback.rating
            current.comment = feedback.comment
            feedback = current
        else:
            self.session.add(feedback)
        await self.session.commit()
        await self.session.refresh(feedback)
        return feedback

    async def get_feedback_for_messages(
        self, message_ids: list[str]
    ) -> dict[str, MessageFeedback]:
        if not message_ids:
            return {}
        result = await self.session.execute(
            select(MessageFeedback).where(MessageFeedback.message_id.in_(message_ids))
        )
        return {f.message_id: f for f in result.scalars().all()}
