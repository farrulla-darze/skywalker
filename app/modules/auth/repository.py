"""Auth persistence layer."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RevokedToken, User


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: str) -> User | None:
        return await self.session.get(User, user_id)

    async def create_user(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def revoke_token(self, jti: str, user_id: str, expires_at: datetime) -> None:
        self.session.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
        await self.session.commit()

    async def is_token_revoked(self, jti: str) -> bool:
        return await self.session.get(RevokedToken, jti) is not None

    async def purge_expired_revocations(self) -> None:
        """Housekeeping: expired tokens no longer need to sit in the denylist."""
        await self.session.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(UTC))
        )
        await self.session.commit()
