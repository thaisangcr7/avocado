"""Workspace routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, WorkspaceServiceDep
from app.schemas.common import MessageResponse
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceStatsResponse,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: CurrentUserDep, service: WorkspaceServiceDep
) -> list[WorkspaceResponse]:
    return await service.list_for_user(user.id)


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, user: CurrentUserDep, service: WorkspaceServiceDep
) -> WorkspaceResponse:
    return await service.create(payload, user.id, user.org_id)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: uuid.UUID, user: CurrentUserDep, service: WorkspaceServiceDep
) -> WorkspaceResponse:
    return await service.get(workspace_id, user.id)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
    user: CurrentUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    return await service.update(workspace_id, payload, user.id)


@router.delete("/{workspace_id}", response_model=MessageResponse)
async def delete_workspace(
    workspace_id: uuid.UUID, user: CurrentUserDep, service: WorkspaceServiceDep
) -> MessageResponse:
    await service.delete(workspace_id, user.id)
    return MessageResponse(message="Workspace deleted.")


@router.get("/{workspace_id}/stats", response_model=WorkspaceStatsResponse)
async def workspace_stats(
    workspace_id: uuid.UUID, user: CurrentUserDep, service: WorkspaceServiceDep
) -> WorkspaceStatsResponse:
    return await service.stats(workspace_id, user.id)
