"""Explicit per-conversation tool choices."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.models.conversations import Conversation
from app.models.tools import ConversationTool
from app.repositories.base import BaseRepository


class ConversationToolRepository(BaseRepository[ConversationTool]):
    model = ConversationTool

    async def belongs_to_workspace(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> bool:
        """Selections hang off a conversation, so the scope check happens there."""
        stmt = select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def choices(self, conversation_id: uuid.UUID) -> dict[str, bool]:
        """Every explicit decision for this conversation. Empty means unset."""
        stmt = select(ConversationTool.tool_slug, ConversationTool.enabled).where(
            ConversationTool.conversation_id == conversation_id
        )
        return dict((await self._session.execute(stmt)).all())  # type: ignore[arg-type]

    async def replace(self, *, conversation_id: uuid.UUID, choices: dict[str, bool]) -> None:
        await self._session.execute(
            delete(ConversationTool).where(ConversationTool.conversation_id == conversation_id)
        )
        for slug, enabled in choices.items():
            self._session.add(
                ConversationTool(conversation_id=conversation_id, tool_slug=slug, enabled=enabled)
            )
        await self._session.flush()
