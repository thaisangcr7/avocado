"""Artifact — something the assistant produced that outlives the message.

A chart, a generated document, a program. Distinct from an uploaded document,
which is something the *user* brought in: conflating the two makes it impossible
to answer "what was this grounded in" versus "what did it make".

Versions are rows, not columns. Editing an artifact — by the model or by hand —
appends a new row pointing at the previous one, so the history is readable and
an earlier version is still retrievable rather than overwritten.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ArtifactAuthor, ArtifactKind


class Artifact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_workspace_created", "workspace_id", "created_at"),
        # The panel lists one row per lineage at its newest version, so both
        # columns are in every listing query.
        Index("ix_artifacts_lineage_version", "lineage_id", "version"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    # Nullable because an artifact can come from the analysis path, which is not
    # attached to a conversation.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Every version of one artifact shares a lineage id. The first version's
    # lineage id is its own id, which keeps "list the newest of each" a plain
    # group-by rather than a recursive walk up parent pointers.
    lineage_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="SET NULL")
    )

    kind: Mapped[ArtifactKind] = mapped_column(
        Enum(
            ArtifactKind,
            name="artifact_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    author: Mapped[ArtifactAuthor] = mapped_column(
        Enum(
            ArtifactAuthor,
            name="artifact_author",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ArtifactAuthor.AI,
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)

    # Text-shaped artifacts live inline: they are small, and holding them here
    # means the panel renders without a second round trip to object storage.
    content: Mapped[str | None] = mapped_column(Text)
    # Binary ones (a rendered chart) live in object storage like any other blob.
    storage_key: Mapped[str | None] = mapped_column(String(700))

    model_used: Mapped[str | None] = mapped_column(String(100))
