"""Data access for message feedback."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.models.conversations import Message
from app.models.enums import FeedbackRating
from app.models.feedback import MessageFeedback
from app.repositories.base import BaseRepository


class MessageFeedbackRepository(BaseRepository[MessageFeedback]):
    model = MessageFeedback

    async def belongs_to_workspace(self, message_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
        """Feedback hangs off a message, so the scope check happens there."""
        stmt = select(Message.id).where(
            Message.id == message_id, Message.workspace_id == workspace_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def set_rating(
        self, *, message_id: uuid.UUID, user_id: uuid.UUID, rating: FeedbackRating | None
    ) -> None:
        """Record, change, or withdraw one reader's opinion.

        `None` withdraws it. Changing your mind updates the row rather than
        adding a second one, so a count of thumbs stays a count of people.
        """
        existing = (
            await self._session.execute(
                select(MessageFeedback).where(
                    MessageFeedback.message_id == message_id,
                    MessageFeedback.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

        if rating is None:
            if existing is not None:
                await self._session.delete(existing)
            await self._session.flush()
            return

        if existing is None:
            self._session.add(
                MessageFeedback(message_id=message_id, user_id=user_id, rating=rating)
            )
        else:
            existing.rating = rating
        await self._session.flush()

    async def ratings_for(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[uuid.UUID, FeedbackRating]:
        """This reader's own ratings across one thread, in a single query."""
        stmt = (
            select(MessageFeedback.message_id, MessageFeedback.rating)
            .join(Message, Message.id == MessageFeedback.message_id)
            .where(Message.conversation_id == conversation_id, MessageFeedback.user_id == user_id)
        )
        return dict((await self._session.execute(stmt)).all())  # type: ignore[arg-type]

    async def clear_for_message(self, message_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(MessageFeedback).where(MessageFeedback.message_id == message_id)
        )
