"""Model catalogue resources — what the UI's model picker renders."""

from __future__ import annotations

from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    provider: str
    display_name: str
    context_window: int
    max_output_tokens: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    supports_vision: bool
    tier: str


class ModelCatalogResponse(BaseModel):
    """Every selectable model, plus the Auto option.

    `auto_available` is false when no provider is configured, which is what
    lets the picker explain itself instead of silently offering nothing.
    """

    models: list[ModelInfo]
    default_provider: str
    auto_available: bool
