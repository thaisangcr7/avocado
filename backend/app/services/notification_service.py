"""Telling someone about something that happened while they were away.

The bar for anything reaching here: it happened when the user was not looking,
and they would want to know. A surface that accepts everything becomes a second
inbox nobody reads, which is worse than not having one.
"""

from __future__ import annotations

import uuid

from app.core.logging import get_logger
from app.models.enums import NotificationKind
from app.models.notifications import Notification
from app.repositories.notifications import NotificationRepository
from app.schemas.notifications import NotificationList, NotificationResponse

log = get_logger(__name__)


class NotificationService:
    def __init__(self, *, notifications: NotificationRepository) -> None:
        self._notifications = notifications

    async def list(self, user_id: uuid.UUID) -> NotificationList:
        rows = await self._notifications.list_for_user(user_id)
        return NotificationList(
            notifications=[NotificationResponse.model_validate(row) for row in rows],
            unread=await self._notifications.unread_count(user_id),
        )

    async def mark_read(
        self, *, user_id: uuid.UUID, notification_id: uuid.UUID | None = None
    ) -> NotificationList:
        await self._notifications.mark_read(user_id=user_id, notification_id=notification_id)
        await self._notifications.commit()
        return await self.list(user_id)


async def notify(
    repository: NotificationRepository,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: NotificationKind,
    title: str,
    body: str | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    """Record one notice, addressed to one person.

    A free function rather than a service method because the caller that
    matters is a background job, which has a session and no service graph.

    Does nothing when there is nobody to tell. A schedule whose creator has
    left still runs; it just has no one to notify, and inventing a recipient
    would put someone else's overnight brief in a stranger's bell.
    """
    if user_id is None:
        return
    await repository.add(
        Notification(
            workspace_id=workspace_id,
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            conversation_id=conversation_id,
        )
    )
