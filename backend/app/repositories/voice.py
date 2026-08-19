"""Voice recording data access."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.tenancy import Team, TeamMembership, Workspace
from app.models.voice import VoiceRecording
from app.repositories.base import WorkspaceScopedRepository


class VoiceRecordingRepository(WorkspaceScopedRepository[VoiceRecording]):
    model = VoiceRecording

    async def get_for_user(
        self, recording_id: uuid.UUID, user_id: uuid.UUID
    ) -> VoiceRecording | None:
        """Fetch a recording by id only if this user can reach its workspace.

        Same pattern as documents: the membership join *is* the access check,
        so the row is never loaded before the caller's right to see it is
        established.
        """
        stmt = (
            select(VoiceRecording)
            .join(Workspace, Workspace.id == VoiceRecording.workspace_id)
            .join(Team, Team.id == Workspace.team_id)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(
                VoiceRecording.id == recording_id,
                TeamMembership.user_id == user_id,
            )
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_for_workspace(
        self, workspace_id: uuid.UUID, *, limit: int = 100
    ) -> list[VoiceRecording]:
        stmt = (
            select(VoiceRecording)
            .where(VoiceRecording.workspace_id == workspace_id)
            .order_by(VoiceRecording.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
