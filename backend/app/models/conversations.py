"""Conversations and messages — the chat surface over the knowledge base."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MessageRole


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Optional link to a task. This is what makes "resume where I left off"
    # possible: a task's thread is a conversation, not a fresh chat.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False, default="New conversation")

    # One person's shortcut, like a preset pin — but a conversation belongs to
    # a workspace rather than to a reader, so this sits on the row rather than
    # in a join table. Revisit if threads become collaborative.
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Out of the way without being gone. Deliberately not a `status` enum with
    # a "completed" state: every chat is complete the moment it stops, so the
    # chip would carry no information. Active or filed away is a real
    # distinction; "completed" is not.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )

    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # [{document_id, document_name, chunk_id, snippet, page, score}] — the
    # grounding for an assistant answer, rendered as clickable sources.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # A whole-workspace executive report, when this message is one. Stored on
    # the message so it re-renders on reload without recomputing the analysis.
    report_artifact: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # True when generation failed and this message records that rather than an
    # answer. The user's turn genuinely happened, so the question stays in the
    # thread; without this the thread shows a question with no reply and no
    # explanation once the transient error notice is gone.
    failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Which model actually answered. Surfaced in the UI so a user on Auto is
    # never left guessing (architecture §10).
    model_used: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    # Which preset this turn ran under, and at which version. Recorded rather
    # than looked up later, because a preset can be edited: without the version
    # a changed prompt would silently rewrite what a past answer was told.
    # SET NULL rather than CASCADE — deleting a preset must not delete history.
    preset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("presets.id", ondelete="SET NULL")
    )
    preset_version: Mapped[int | None] = mapped_column(Integer)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
