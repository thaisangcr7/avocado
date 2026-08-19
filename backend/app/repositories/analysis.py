"""Analysis run data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.analysis import AnalysisRun
from app.models.tenancy import Team, TeamMembership, Workspace
from app.repositories.base import WorkspaceScopedRepository


class AnalysisRunRepository(WorkspaceScopedRepository[AnalysisRun]):
    model = AnalysisRun

    async def get_for_user(self, run_id: uuid.UUID, user_id: uuid.UUID) -> AnalysisRun | None:
        """Fetch a run by id only if this user can reach its workspace.

        Same reasoning as `DocumentRepository.get_for_user`: the access check
        is the join, not a later comparison.
        """
        stmt = (
            select(AnalysisRun)
            .join(Workspace, Workspace.id == AnalysisRun.workspace_id)
            .join(Team, Team.id == Workspace.team_id)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(AnalysisRun.id == run_id, TeamMembership.user_id == user_id)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID, *, limit: int = 50
    ) -> list[AnalysisRun]:
        stmt = (
            select(AnalysisRun)
            .where(
                AnalysisRun.document_id == document_id,
                AnalysisRun.workspace_id == workspace_id,
            )
            .order_by(AnalysisRun.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
