"""Tool registry resources."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import ToolCategory, ToolKind
from app.schemas.common import ApiModel


class ToolResponse(ApiModel):
    slug: str
    name: str
    description: str
    category: ToolCategory
    kind: ToolKind
    context_cost_tokens: int
    enabled: bool
    # False for a tool that is declared but not wired to anything yet. The UI
    # shows it and refuses to switch it on, rather than hiding it or letting it
    # fail at call time.
    connected: bool
    # Vendors that can run it. Empty means any. A tool listed here is reported
    # as off when the answering model comes from somewhere else, rather than
    # appearing on and doing nothing.
    runs_on: list[str] = []
    # Whether a connected server answered when last asked. None for anything
    # that is not a remote server — a built-in has no separate thing to be
    # reachable, and reporting False there would read as broken.
    reachable: bool | None = None
    # How many tools it offered. Shown so "connected" means something more than
    # a row in a config file.
    tool_count: int | None = None


class ToolSelectionResponse(ApiModel):
    tools: list[ToolResponse]
    enabled_count: int
    # What the enabled set adds to every request, whether or not it is called.
    context_cost_tokens: int


class ToolSelectionUpdate(BaseModel):
    slugs: list[str] = Field(default_factory=list, max_length=40)
