"""Conversation and message resources."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import MessageRole
from app.schemas.common import ApiModel


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    task_id: uuid.UUID | None = None


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ConversationResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID | None
    task_id: uuid.UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


class Citation(BaseModel):
    """One grounding source behind an answer.

    `snippet` is the retrieved text itself, so the UI can show what the answer
    was based on without a second fetch.
    """

    document_id: uuid.UUID
    document_name: str
    chunk_id: uuid.UUID
    snippet: str
    score: float
    page: int | None = None
    sheet: str | None = None
    section: str | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    # Restrict retrieval to specific documents. Empty means the whole workspace.
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class MessageResponse(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[dict] = []
    # True when this records a failed generation rather than an answer.
    failed: bool = False
    model_used: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class ChatTurnResponse(BaseModel):
    """Both halves of a turn, so the client renders without a refetch."""

    user_message: MessageResponse
    assistant_message: MessageResponse
