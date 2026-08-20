"""Document, chunk and table data access, including vector retrieval."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select, update

from app.models.documents import Document, DocumentChunk, DocumentTable
from app.models.enums import DocumentStatus
from app.models.tenancy import Team, TeamMembership, Workspace
from app.repositories.base import WorkspaceScopedRepository


class DocumentRepository(WorkspaceScopedRepository[Document]):
    model = Document

    async def get_for_user(self, document_id: uuid.UUID, user_id: uuid.UUID) -> Document | None:
        """Fetch a document by id only if this user can reach its workspace.

        The API exposes `/documents/{id}` without a workspace in the path, so
        the access check has to happen here. Doing it as a join rather than a
        follow-up query means the row is never loaded before the caller's right
        to see it is established — there is no window where an unauthorised
        document exists in memory.
        """
        stmt = (
            select(Document)
            .join(Workspace, Workspace.id == Document.workspace_id)
            .join(Team, Team.id == Workspace.team_id)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(Document.id == document_id, TeamMembership.user_id == user_id)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def find_by_checksum(self, workspace_id: uuid.UUID, checksum: str) -> Document | None:
        """Locate an identical prior upload.

        Re-uploading the same file is common (someone re-sends an attachment);
        surfacing the existing document beats silently ingesting a duplicate
        and diluting retrieval with two copies of everything.
        """
        stmt = select(Document).where(
            Document.workspace_id == workspace_id,
            Document.checksum_sha256 == checksum,
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def set_status(
        self,
        document_id: uuid.UUID,
        workspace_id: uuid.UUID,
        status: DocumentStatus,
        *,
        error_message: str | None = None,
    ) -> None:
        stmt = (
            update(Document)
            .where(Document.id == document_id, Document.workspace_id == workspace_id)
            .values(status=status, error_message=error_message)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_recent_failed(
        self, workspace_id: uuid.UUID, *, limit: int = 10
    ) -> list[Document]:
        """Documents that failed ingestion.

        A failed document is invisible to retrieval, so whoever uploaded it
        needs telling — otherwise they just experience the answers as missing.
        """
        stmt = (
            select(Document)
            .where(
                Document.workspace_id == workspace_id,
                Document.status == DocumentStatus.FAILED,
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_ready(self, workspace_id: uuid.UUID) -> list[Document]:
        stmt = (
            select(Document)
            .where(
                Document.workspace_id == workspace_id,
                Document.status == DocumentStatus.READY,
            )
            .order_by(Document.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())


class ChunkRepository(WorkspaceScopedRepository[DocumentChunk]):
    model = DocumentChunk

    async def bulk_add(self, chunks: list[DocumentChunk]) -> None:
        self._session.add_all(chunks)
        await self._session.flush()

    async def delete_for_document(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        stmt = delete(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.workspace_id == workspace_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_visible_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID, *, limit: int = 20
    ) -> list[DocumentChunk]:
        """A document's chunks in order — its opening text, reassembled."""
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.workspace_id == workspace_id,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def search(
        self,
        *,
        workspace_id: uuid.UUID,
        embedding: list[float],
        embedding_model: str,
        limit: int = 8,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[DocumentChunk, float, str]]:
        """Nearest chunks by cosine distance, within one workspace.

        The `workspace_id` predicate sits on the chunk table itself, so tenant
        isolation is part of the same scan as the vector search rather than a
        filter applied to results afterwards.

        `embedding_model` restricts the scan to chunks embedded in the same
        vector space as the query. Without it, switching providers would rank
        the query against vectors it cannot be compared to and return confident
        nonsense; with it, the switch reads as "nothing indexed yet" until the
        corpus is re-embedded.

        Returns (chunk, similarity, document filename). Similarity is
        `1 - cosine_distance`, so higher is better.
        """
        distance = DocumentChunk.embedding.cosine_distance(embedding)
        stmt = (
            select(DocumentChunk, distance.label("distance"), Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.workspace_id == workspace_id,
                DocumentChunk.embedding.is_not(None),
                DocumentChunk.embedding_model == embedding_model,
            )
        )
        if document_ids:
            stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))

        stmt = stmt.order_by(distance).limit(limit)
        rows = (await self._session.execute(stmt)).all()
        return [(chunk, 1.0 - float(dist), filename) for chunk, dist, filename in rows]


class DocumentTableRepository(WorkspaceScopedRepository[DocumentTable]):
    model = DocumentTable

    async def list_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[DocumentTable]:
        stmt = (
            select(DocumentTable)
            .where(
                DocumentTable.document_id == document_id,
                DocumentTable.workspace_id == workspace_id,
            )
            .order_by(DocumentTable.sheet_index)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[str]:
        """Delete table rows, returning their storage keys so the caller can
        clean up the objects they point at."""
        existing = await self.list_for_document(document_id, workspace_id)
        keys = [t.storage_key for t in existing]
        stmt = delete(DocumentTable).where(
            DocumentTable.document_id == document_id,
            DocumentTable.workspace_id == workspace_id,
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return keys

    async def bulk_add(self, tables: list[DocumentTable]) -> None:
        self._session.add_all(tables)
        await self._session.flush()

    @staticmethod
    def schema_summary(table: DocumentTable) -> dict[str, Any]:
        """The compact schema handed to the model for code generation.

        Column names, types and a few sample values — enough to write correct
        pandas, without shipping the data itself into the prompt.
        """
        return {
            "table": table.name,
            "variable": table.name,
            "rows": table.row_count,
            "columns": table.columns,
        }
