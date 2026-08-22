"""Artifact reads and writes, scoped to a workspace.

Listing shows one row per artifact at its newest version, not every version of
everything — a panel that grew a row each time the model revised a document
would be unreadable by the third edit.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.artifacts import Artifact
from app.repositories.base import WorkspaceScopedRepository


class ArtifactRepository(WorkspaceScopedRepository[Artifact]):
    model = Artifact

    async def latest_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Artifact]:
        """Newest version of each artifact, most recently created first."""
        newest = (
            select(
                Artifact.lineage_id,
                func.max(Artifact.version).label("version"),
            )
            .where(Artifact.workspace_id == workspace_id)
            .group_by(Artifact.lineage_id)
            .subquery()
        )

        stmt = (
            select(Artifact)
            .join(
                newest,
                (Artifact.lineage_id == newest.c.lineage_id)
                & (Artifact.version == newest.c.version),
            )
            .where(Artifact.workspace_id == workspace_id)
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        )
        if conversation_id is not None:
            stmt = stmt.where(Artifact.conversation_id == conversation_id)

        return list((await self._session.execute(stmt)).scalars().all())

    async def versions(self, lineage_id: uuid.UUID, workspace_id: uuid.UUID) -> list[Artifact]:
        """Every version of one artifact, oldest first."""
        stmt = (
            self._scoped_select(workspace_id)
            .where(Artifact.lineage_id == lineage_id)
            .order_by(Artifact.version.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def latest_version_number(
        self, lineage_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> int | None:
        """Highest version in a lineage, or None when the lineage is unknown.

        Read inside the same transaction as the insert that uses it, so two
        concurrent edits cannot both think they are version 3.
        """
        stmt = select(func.max(Artifact.version)).where(
            Artifact.lineage_id == lineage_id,
            Artifact.workspace_id == workspace_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
