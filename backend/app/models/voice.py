"""Voice recordings (architecture §9, phase 2).

A finished transcript is treated as an ordinary document — chunked, embedded,
and retrievable like any other source — so this table only tracks the audio
artifact and its transcription state.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TranscriptStatus


class VoiceRecording(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "voice_recordings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # The document row created from the finished transcript, once there is one.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )

    storage_path: Mapped[str] = mapped_column(String(700), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    transcript_status: Mapped[TranscriptStatus] = mapped_column(
        Enum(
            TranscriptStatus,
            name="transcript_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TranscriptStatus.PENDING,
    )
    transcript: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
