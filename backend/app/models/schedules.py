"""A prompt that runs on its own, on a schedule.

The thing a user actually wants from this is "tell me what changed overnight"
without having to remember to ask. So a schedule is a prompt, a recurrence, and
optionally a preset to run it under — the same instruction they would have
typed, just fired by a clock.

Each run opens a conversation and sends the prompt, which means the result
lands where every other answer lands: in history, with its citations, readable
later. Nothing about a scheduled answer is a special kind of object.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Schedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "schedules"
    __table_args__ = (
        # The executor's only query: everything due, soonest first. Enabled is
        # in the index because a disabled schedule must cost nothing to skip.
        Index("ix_schedules_due", "enabled", "next_run_at"),
        Index("ix_schedules_workspace", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # The instruction to run it under, if any. SET NULL rather than CASCADE:
    # deleting a preset should not silently delete the schedules using it — it
    # should leave them running plainly, which is visible and recoverable.
    preset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("presets.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    cron: Mapped[str] = mapped_column(String(120), nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # When it next comes due. Stored rather than computed per sweep, so the
    # executor's query is an index scan on a timestamp instead of parsing every
    # cron expression in the table on every tick.
    next_run_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_run_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # What happened on the last run, in a sentence. A schedule that has been
    # failing quietly for a week is the failure mode worth designing against.
    last_error: Mapped[str | None] = mapped_column(Text)
