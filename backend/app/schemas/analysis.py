"""Analysis resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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
