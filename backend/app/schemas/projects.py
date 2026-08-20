"""Project, task and suggestion resources."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    DocumentKind,
    ProjectStatus,
    ProjectVisibility,
    SuggestionKind,
    TaskStatus,
)
from app.schemas.common import ApiModel

# --- projects --------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=4000)
    # Restricted by default. Opening a board to the whole workspace is an
    # explicit choice, never inherited from document visibility (§11).
    visibility: ProjectVisibility = ProjectVisibility.RESTRICTED
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus | None = None
    visibility: ProjectVisibility | None = None


class ProjectResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    goal: str | None
    status: ProjectStatus
    visibility: ProjectVisibility
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectDetailResponse(ProjectResponse):
    member_ids: list[uuid.UUID] = []
    # Task counts per status, so a board header needs no second request.
    task_counts: dict[str, int] = {}


# --- tasks -----------------------------------------------------------------


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=8000)
    assignee_id: uuid.UUID | None = None
    status: TaskStatus = TaskStatus.TODO
    due_date: date | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = Field(default=None, max_length=8000)
    assignee_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    due_date: date | None = None


class TaskResponse(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workspace_id: uuid.UUID
    assignee_id: uuid.UUID | None
    title: str
    notes: str | None
    status: TaskStatus
    due_date: date | None
    created_at: datetime
    updated_at: datetime


class TaskResumeResponse(BaseModel):
    """Where a task stood when it was last touched.

    The point of §11: returning to a task after two days on something else
    should start with "here is where we left off", not a blank chat.
    """

    task: TaskResponse
    # The task's own thread, created on demand if it had none.
    conversation_id: uuid.UUID
    summary: str
    message_count: int
    last_activity_at: datetime | None
    # False when the summary is a deterministic fallback rather than written by
    # a model — so the UI never implies more synthesis than actually happened.
    synthesized: bool


# --- suggestions -----------------------------------------------------------


class Suggestion(BaseModel):
    """One proactive nudge.

    Deliberately not persisted (§5): suggestions are a digest, not a record.
    `id` is a stable content hash so the client can remember a dismissal
    without the server keeping one.
    """

    id: str
    kind: SuggestionKind
    title: str
    detail: str | None = None
    # Where the nudge points, so it is actionable rather than merely informative.
    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    priority: int = 0


class SuggestionsResponse(BaseModel):
    items: list[Suggestion]
    generated_at: datetime
    # True when this came from the cache rather than being recomputed.
    cached: bool = False
    # The model that phrased them, or null when the deterministic wording was
    # used — the same honesty as `model_used` on a message.
    model_used: str | None = None


# --- org knowledge ---------------------------------------------------------


class ClassificationResponse(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    team_id: uuid.UUID | None
    kind: DocumentKind
    title: str | None
    summary: str | None
    topics: list[str]
    effective_date: date | None
    confidence: float
    model_used: str | None
    version: int


class ClassifiedDocument(BaseModel):
    """A classification with enough of its document to render a row."""

    document_id: uuid.UUID
    filename: str
    kind: DocumentKind
    title: str | None
    summary: str | None
    topics: list[str]
    effective_date: date | None
    team_id: uuid.UUID | None
    created_at: datetime


class KnowledgeMapResponse(BaseModel):
    """What this team does, as derived from what it has uploaded."""

    counts_by_kind: dict[str, int]
    topics: list[str]
    documents: list[ClassifiedDocument]
    unclassified_count: int


class GeneratedClassification(BaseModel):
    """The structured output requested from the model for tagging."""

    kind: DocumentKind
    title: str = Field(max_length=300)
    summary: str = Field(max_length=2000)
    topics: list[str] = Field(default_factory=list, max_length=8)
    effective_date: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
