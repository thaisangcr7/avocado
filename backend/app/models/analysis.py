"""AnalysisRun — one row per analysis-agent invocation.

Doubles as the audit log for code execution: the generated code, what it
produced, and how long it ran are all retained, so an answer can always be
traced back to the exact program that computed it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AnalysisStatus


class AnalysisRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    generated_code: Mapped[str | None] = mapped_column(Text)
    code_explanation: Mapped[str | None] = mapped_column(Text)

    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(
            AnalysisStatus,
            name="analysis_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AnalysisStatus.PENDING,
    )

    result_summary: Mapped[str | None] = mapped_column(Text)
    # {"stdout": str, "tables": [{columns, rows}], "scalars": {...}}
    result_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    chart_url: Mapped[str | None] = mapped_column(String(700))
    error_message: Mapped[str | None] = mapped_column(Text)

    model_used: Mapped[str | None] = mapped_column(String(100))
    execution_ms: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
