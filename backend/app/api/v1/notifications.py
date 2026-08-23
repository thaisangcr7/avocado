"""Notification routes — the bell.

Addressed to the authenticated user, so there is no workspace in the path: a
person's notifications follow them across the Spaces they belong to.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, NotificationServiceDep
from app.schemas.notifications import NotificationList

router = APIRouter(tags=["notifications"], prefix="/notifications")


@router.get("", response_model=NotificationList)
async def list_notifications(
    user: CurrentUserDep, service: NotificationServiceDep
) -> NotificationList:
    return await service.list(user.id)


@router.put("/read", response_model=NotificationList)
async def mark_all_read(user: CurrentUserDep, service: NotificationServiceDep) -> NotificationList:
    return await service.mark_read(user_id=user.id)


@router.put("/{notification_id}/read", response_model=NotificationList)
async def mark_read(
    notification_id: uuid.UUID,
    user: CurrentUserDep,
    service: NotificationServiceDep,
) -> NotificationList:
    return await service.mark_read(user_id=user.id, notification_id=notification_id)
