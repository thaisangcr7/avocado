"""Notification resources."""

from __future__ import annotations

import datetime
import uuid

from app.models.enums import NotificationKind
from app.schemas.common import ApiModel


class NotificationResponse(ApiModel):
    id: uuid.UUID
    kind: NotificationKind
    title: str
    body: str | None
    conversation_id: uuid.UUID | None
    # Null means unread. A timestamp rather than a flag, because "when did they
    # see this" is the question that gets asked later.
    read_at: datetime.datetime | None
    created_at: datetime.datetime


class NotificationList(ApiModel):
    notifications: list[NotificationResponse]
    unread: int
