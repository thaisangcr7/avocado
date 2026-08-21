"""Analysis resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AnalysisStatus
from app.schemas.common import ApiModel


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # Which sheet to analyse. Omitted means the document's first/only table.
    table_id: uuid.UUID | None = None


class AnalysisTable(BaseModel):
    name: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int = 0
    truncated: bool = False


class AnalysisRunResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    question: str
    status: AnalysisStatus
    # The generated program is part of the response, not hidden: the user can
    # read exactly what produced the number, and re-run or tweak it.
    generated_code: str | None
    code_explanation: str | None
    result_summary: str | None
    result_data: dict[str, Any]
    chart_url: str | None
    error_message: str | None
    model_used: str | None
    execution_ms: int | None
    attempt_count: int
    created_at: datetime


class GeneratedAnalysis(BaseModel):
    """The structured output requested from the model for code generation."""

    code: str = Field(max_length=20000)
    explanation: str = Field(max_length=2000)


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualizationEncoding(StrictAnalysisModel):
    """One safe field binding in a visualization.

    The model chooses semantics, not executable JavaScript or arbitrary
    Vega expressions. The service validates every field against computed
    result columns before this contract reaches the browser.
    """

    field: str = Field(min_length=1, max_length=200)
    type: Literal["nominal", "ordinal", "temporal", "quantitative"]
    title: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, max_length=40)


class AnalysisVisualization(StrictAnalysisModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    mark: Literal["bar", "line", "area", "point", "arc", "boxplot"]
    table_index: int = Field(default=0, ge=0, le=5)
    x: VisualizationEncoding
    y: VisualizationEncoding
    color: VisualizationEncoding | None = None
    interactive: bool = True


class AnalysisMetric(StrictAnalysisModel):
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=120)
    context: str | None = Field(default=None, max_length=240)
    tone: Literal["neutral", "positive", "negative", "warning"] = "neutral"


class AnalysisPresentation(StrictAnalysisModel):
    """Dashboard instructions generated from computed evidence only."""

    summary: str = Field(min_length=1, max_length=4000)
    metrics: list[AnalysisMetric] = Field(default_factory=list, max_length=6)
    visualizations: list[AnalysisVisualization] = Field(default_factory=list, max_length=3)
