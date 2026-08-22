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


class ToolSelectionResponse(ApiModel):
    tools: list[ToolResponse]
    enabled_count: int
    # What the enabled set adds to every request, whether or not it is called.
    context_cost_tokens: int


class ToolSelectionUpdate(BaseModel):
    slugs: list[str] = Field(default_factory=list, max_length=40)
