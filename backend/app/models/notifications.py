"""Something worth telling a person about after the fact.

The first real source is a schedule: it runs while nobody is watching, so
without this its answer sits in history unread and the feature may as well not
have run. That is the bar for anything added here — it happened when the user
was not looking, and they would want to know.

Addressed to a user rather than broadcast to a workspace. "Your overnight brief
is ready" is not news to the colleague who did not create the schedule.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import NotificationKind


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        # The bell's only two queries: this person's newest, and how many are
        # unread. Both are covered by this one index.
        Index("ix_notifications_user_read", "user_id", "read_at", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[NotificationKind] = mapped_column(
        Enum(
            NotificationKind,
            name="notification_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)

    # Where clicking it goes. SET NULL so deleting a conversation leaves the
    # notice readable rather than deleting the record that it happened.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )

    # Null means unread. A timestamp rather than a boolean, because "when did
    # they see this" is the question that actually gets asked later.
    read_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
