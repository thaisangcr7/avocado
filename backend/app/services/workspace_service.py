"""Workspace lifecycle and the one place workspace access is decided.

`require_access` is called by the router dependency for every workspace-scoped
route, so authorisation happens once, before a service ever sees the id.
"""

from __future__ import annotations

import uuid

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.models.enums import Role
from app.models.tenancy import Team, Workspace
from app.repositories.analysis import AnalysisRunRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.documents import ChunkRepository, DocumentRepository
from app.repositories.tenancy import (
    MembershipRepository,
    TeamRepository,
    WorkspaceRepository,
)
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceStatsResponse,
    WorkspaceUpdate,
)


class WorkspaceService:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRepository,
        teams: TeamRepository,
        memberships: MembershipRepository,
        documents: DocumentRepository | None = None,
        chunks: ChunkRepository | None = None,
        conversations: ConversationRepository | None = None,
        analysis_runs: AnalysisRunRepository | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._teams = teams
        self._memberships = memberships
        self._documents = documents
        self._chunks = chunks
        self._conversations = conversations
        self._analysis_runs = analysis_runs

    async def require_access(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        minimum_role: Role = Role.VIEWER,
    ) -> Workspace:
        """Resolve a workspace the user may reach, or refuse.

        A workspace the caller cannot access is reported as 404, not 403:
        confirming that an id exists is itself information a non-member should
        not get.
        """
        workspace = await self._workspaces.get_for_user(workspace_id, user_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")

        if minimum_role is not Role.VIEWER:
            membership = await self._memberships.get_for_user_and_team(user_id, workspace.team_id)
            if membership is None or not membership.role.at_least(minimum_role):
                raise PermissionDeniedError(
                    f"This action requires the '{minimum_role.value}' role."
                )
        return workspace

    async def list_for_user(self, user_id: uuid.UUID) -> list[WorkspaceResponse]:
        workspaces = await self._workspaces.list_for_user(user_id)
        return [WorkspaceResponse.model_validate(w) for w in workspaces]

    async def create(
        self, payload: WorkspaceCreate, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> WorkspaceResponse:
        team = await self._resolve_team(payload.team_id, user_id, org_id)
        workspace = await self._workspaces.add(
            Workspace(
                team_id=team.id,
                name=payload.name,
                description=payload.description,
                preferred_model=payload.preferred_model,
            )
        )
        await self._workspaces.commit()
        return WorkspaceResponse.model_validate(workspace)

    async def _resolve_team(
        self, team_id: uuid.UUID | None, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Team:
        memberships = await self._memberships.list_for_user(user_id)
        if not memberships:
            raise PermissionDeniedError("You do not belong to a team.")

        if team_id is None:
            team = await self._teams.get(memberships[0].team_id)
            if team is None:
                raise NotFoundError("Team not found.")
            return team

        # Membership is the check — an id from the request body is not trusted.
        if not any(m.team_id == team_id for m in memberships):
            raise PermissionDeniedError("You do not belong to that team.")
        team = await self._teams.get(team_id)
        if team is None or team.org_id != org_id:
            raise NotFoundError("Team not found.")
        return team

    async def get(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> WorkspaceResponse:
        workspace = await self.require_access(workspace_id, user_id)
        return WorkspaceResponse.model_validate(workspace)

    async def update(
        self, workspace_id: uuid.UUID, payload: WorkspaceUpdate, user_id: uuid.UUID
    ) -> WorkspaceResponse:
        workspace = await self.require_access(workspace_id, user_id, minimum_role=Role.MEMBER)
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(workspace, field, value)
        await self._workspaces.commit()
        await self._workspaces.refresh(workspace)
        return WorkspaceResponse.model_validate(workspace)

    async def delete(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        workspace = await self.require_access(workspace_id, user_id, minimum_role=Role.TEAM_ADMIN)
        await self._workspaces.delete(workspace)
        await self._workspaces.commit()

    async def stats(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> WorkspaceStatsResponse:
        await self.require_access(workspace_id, user_id)
        if not (self._documents and self._chunks and self._conversations and self._analysis_runs):
            raise ValidationError("Statistics are unavailable.")

        ready = await self._documents.list_ready(workspace_id)
        return WorkspaceStatsResponse(
            workspace_id=workspace_id,
            document_count=await self._documents.count(workspace_id),
            ready_document_count=len(ready),
            chunk_count=await self._chunks.count(workspace_id),
            conversation_count=await self._conversations.count(workspace_id),
            analysis_run_count=await self._analysis_runs.count(workspace_id),
        )
