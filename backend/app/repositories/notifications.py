"""Data access for notifications."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select, update

from app.models.notifications import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int = 30) -> list[Notification]:
        """Newest first. Read and unread together — the bell shows both."""
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def unread_count(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def mark_read(
        self, *, user_id: uuid.UUID, notification_id: uuid.UUID | None = None
    ) -> int:
        """Mark one, or everything unread. Returns how many changed.

        Scoped by `user_id` even when an id is given: a notification belongs to
        a person, and an id alone must not let one user clear another's bell.
        """
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=now)
        )
        if notification_id is not None:
            stmt = stmt.where(Notification.id == notification_id)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount or 0
