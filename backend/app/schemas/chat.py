"""Conversation and message resources."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import FeedbackRating, MessageRole
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
    pinned: bool = False
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    # Counted alongside the row rather than fetched per row. Null where the
    # caller did not ask for a history page and nothing counted it.
    message_count: int | None = None


class ConversationPage(ApiModel):
    """One page of history, with enough to render numbered pagination."""

    conversations: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class FeedbackRequest(BaseModel):
    """`None` withdraws a rating, which is different from never having given one."""

    rating: FeedbackRating | None = None


class ConversationFlags(BaseModel):
    """Pin or file away. Both optional: sending one must not reset the other."""

    pinned: bool | None = None
    archived: bool | None = None


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
    # Apply a preset to this turn, by its slash command. Deliberately the slug
    # and not the prompt: the text is read from the row server-side, so a
    # client cannot post its own system prompt and drop the honesty rules.
    preset_slug: str | None = Field(default=None, max_length=80)


class MessageResponse(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[dict] = []
    # A whole-workspace executive report artifact, when this message is one.
    report_artifact: dict | None = None
    # True when this records a failed generation rather than an answer.
    failed: bool = False
    # Which preset this turn ran under, at which version. Null for most turns.
    preset_id: uuid.UUID | None = None
    preset_version: int | None = None
    # This reader's own rating, not a tally. Two people can disagree about the
    # same answer, and showing someone else's thumb as theirs would be a lie.
    feedback: FeedbackRating | None = None
    model_used: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class ChatTurnResponse(BaseModel):
    """Both halves of a turn, so the client renders without a refetch."""

    user_message: MessageResponse
    assistant_message: MessageResponse
