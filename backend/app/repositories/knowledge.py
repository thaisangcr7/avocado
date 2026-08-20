"""Document classification data access — the org knowledge layer."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.documents import Document
from app.models.enums import DocumentKind
from app.models.knowledge import DocumentClassification
from app.repositories.base import WorkspaceScopedRepository


class ClassificationRepository(WorkspaceScopedRepository[DocumentClassification]):
    model = DocumentClassification

    async def get_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> DocumentClassification | None:
        stmt = select(DocumentClassification).where(
            DocumentClassification.document_id == document_id,
            DocumentClassification.workspace_id == workspace_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_kind(
        self,
        workspace_id: uuid.UUID,
        *,
        kind: DocumentKind | None = None,
        team_id: uuid.UUID | None = None,
        topic: str | None = None,
    ) -> list[tuple[DocumentClassification, Document]]:
        """Classifications with their documents, in one query.

        Joined because the answer to "what governs this team?" is a list of
        *documents* — the classification alone has no filename to show.
        """
        stmt = (
            select(DocumentClassification, Document)
            .join(Document, Document.id == DocumentClassification.document_id)
            .where(DocumentClassification.workspace_id == workspace_id)
        )
        if kind is not None:
            stmt = stmt.where(DocumentClassification.kind == kind)
        if team_id is not None:
            stmt = stmt.where(DocumentClassification.team_id == team_id)
        if topic is not None:
            # Containment against the JSONB array, so the index can be used
            # rather than every row being deserialised in Python.
            stmt = stmt.where(DocumentClassification.topics.contains([topic]))

        stmt = stmt.order_by(
            DocumentClassification.effective_date.desc().nullslast(),
            Document.created_at.desc(),
        )
        return [tuple(row) for row in (await self._session.execute(stmt)).all()]

    async def counts_by_kind(self, workspace_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(DocumentClassification.kind, func.count())
            .where(DocumentClassification.workspace_id == workspace_id)
            .group_by(DocumentClassification.kind)
        )
        rows = (await self._session.execute(stmt)).all()
        counts = {kind.value: 0 for kind in DocumentKind}
        for kind, count in rows:
            counts[kind.value] = count
        return counts

    async def topics(self, workspace_id: uuid.UUID) -> list[str]:
        """Every distinct topic in the workspace, for filter chips."""
        stmt = (
            select(func.jsonb_array_elements_text(DocumentClassification.topics))
            .where(DocumentClassification.workspace_id == workspace_id)
            .distinct()
        )
        return sorted((await self._session.execute(stmt)).scalars().all())

    async def unclassified_document_ids(
        self, workspace_id: uuid.UUID, *, limit: int = 100
    ) -> list[uuid.UUID]:
        """Ready documents that have never been classified.

        Used to backfill after the feature is switched on, so a workspace that
        was populated before Phase 4 is not permanently invisible to the
        knowledge layer.
        """
        classified = select(DocumentClassification.document_id).where(
            DocumentClassification.workspace_id == workspace_id
        )
        stmt = (
            select(Document.id)
            .where(
                Document.workspace_id == workspace_id,
                Document.status == "ready",
                Document.id.notin_(classified),
            )
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
