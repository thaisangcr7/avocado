"""Artifact resources — the public contract for generated documents."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ArtifactAuthor, ArtifactKind
from app.schemas.common import ApiModel

# An artifact is held inline and shipped to the browser on every open, so it
# needs a ceiling. Generous enough for a full single-file dashboard, small
# enough that one artifact cannot become a denial of service.
MAX_ARTIFACT_BYTES = 512_000


class ArtifactForCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    filename: str = Field(min_length=1, max_length=300)
    kind: ArtifactKind
    content: str = Field(min_length=1, max_length=MAX_ARTIFACT_BYTES)
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None


class ArtifactForUpdate(BaseModel):
    """A new version of an existing artifact.

    Title is optional because most edits change only the body; leaving it out
    carries the previous version's title forward rather than clearing it.
    """

    content: str = Field(min_length=1, max_length=MAX_ARTIFACT_BYTES)
    title: str | None = Field(default=None, min_length=1, max_length=300)


class ArtifactVersionResponse(ApiModel):
    id: uuid.UUID
    version: int
    author: ArtifactAuthor
    model_used: str | None
    created_at: datetime


class ArtifactResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID | None
    lineage_id: uuid.UUID
    version: int
    kind: ArtifactKind
    author: ArtifactAuthor
    title: str
    filename: str
    content: str | None
    model_used: str | None
    created_at: datetime
    updated_at: datetime


class ArtifactDetailResponse(ArtifactResponse):
    """One artifact plus the shape of its history, for the version picker."""

    versions: list[ArtifactVersionResponse]
