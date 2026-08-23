"""What a reader thought of an answer.

The only honest signal this product gets about answer quality. Retrieval
metrics measure whether the right chunks came back; they cannot measure whether
the answer built from them was any use.

One row per reader per message, so two people can disagree about the same
answer and both be recorded. Changing your mind updates the row rather than
adding a second one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FeedbackRating


class MessageFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_feedback_pair"),)

    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(
            FeedbackRating,
            name="feedback_rating",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
