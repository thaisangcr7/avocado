"""Workspace resources — separate models per operation."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    # Null means "Auto" — the router picks per request.
    preferred_model: str | None = Field(default=None, max_length=100)
    team_id: uuid.UUID | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    preferred_model: str | None = Field(default=None, max_length=100)


class WorkspaceResponse(ApiModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    description: str | None
    preferred_model: str | None
    created_at: datetime
    updated_at: datetime


class WorkspaceStatsResponse(BaseModel):
    workspace_id: uuid.UUID
    document_count: int
    ready_document_count: int
    chunk_count: int
    conversation_count: int
    analysis_run_count: int
