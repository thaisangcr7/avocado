"""Conversation and message data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.conversations import Conversation, Message
from app.repositories.base import WorkspaceScopedRepository


class ConversationRepository(WorkspaceScopedRepository[Conversation]):
    model = Conversation

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.workspace_id == workspace_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())


class MessageRepository(WorkspaceScopedRepository[Message]):
    model = Message

    async def list_for_conversation(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID, *, limit: int = 200
    ) -> list[Message]:
        """Messages in chronological order.

        Scoped by workspace as well as conversation: a conversation id alone is
        a client-supplied value, and this is the layer that refuses to trust it.
        """
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.workspace_id == workspace_id,
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def recent_history(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID, *, limit: int = 12
    ) -> list[Message]:
        """The last N messages, oldest-first — the window sent to the model."""
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.workspace_id == workspace_id,
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return list(reversed(rows))
