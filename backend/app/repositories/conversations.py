"""Conversation and message data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.conversations import Conversation, Message
from app.models.enums import MessageRole
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

    async def get_for_task(
        self, task_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Conversation | None:
        """The thread attached to a task, if it has one."""
        stmt = select(Conversation).where(
            Conversation.task_id == task_id,
            Conversation.workspace_id == workspace_id,
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def unfinished_for_user(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, *, limit: int = 5
    ) -> list[Conversation]:
        """Threads this user started where the last word was theirs.

        A conversation whose final message is from the user is one they asked
        something in and never came back to — which is exactly the thing worth
        nudging them about.
        """
        last_message = (
            select(
                Message.conversation_id,
                func.max(Message.created_at).label("last_at"),
            )
            .group_by(Message.conversation_id)
            .subquery()
        )
        stmt = (
            select(Conversation)
            .join(last_message, last_message.c.conversation_id == Conversation.id)
            .join(
                Message,
                (Message.conversation_id == Conversation.id)
                & (Message.created_at == last_message.c.last_at),
            )
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.user_id == user_id,
                Message.role == MessageRole.USER,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().unique().all())


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
