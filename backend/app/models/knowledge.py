"""The org knowledge layer: what a document *is* to the team.

Architecture §5 describes a tagging pass that turns ingested files into a map
of a team's policies and processes. This is that classification, kept in one
table with a `kind` discriminator rather than separate `PolicyDocument` and
`Process` tables — the two would carry identical structure, and a discriminator
keeps "show me everything this team is governed by" a single query instead of a
union.

Versioning is represented but not yet derived: `supersedes_document_id` exists
so a newer policy can point at the one it replaces, and `version` counts
reclassifications of the same document. Automatically *detecting* that one
document supersedes another needs identity resolution across documents, which
is a genuinely harder problem and deliberately not attempted here.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentKind


class DocumentClassification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "document_classifications"
    __table_args__ = (
        Index("ix_document_classifications_workspace_kind", "workspace_id", "kind"),
        Index("ix_document_classifications_team", "team_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    # One classification per document; re-running the pass updates this row and
    # bumps `version` rather than accumulating rows nothing reads.
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    # Which team this governs. Nullable: plenty of documents are not any one
    # team's, and guessing would be worse than leaving it open.
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )

    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DocumentKind.OTHER,
    )
    title: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    # Free-form subject tags — "expenses", "onboarding", "security".
    topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # When the policy or process took effect, if the document says so. This is
    # what makes "which of these is current?" answerable.
    effective_date: Mapped[date | None] = mapped_column(Date)
    supersedes_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    model_used: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
