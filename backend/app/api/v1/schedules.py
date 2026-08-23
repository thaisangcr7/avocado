"""Schedule routes — prompts that run on their own."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import ScheduleServiceDep, WorkspaceContextDep
from app.schemas.schedules import ScheduleCreate, ScheduleResponse, ScheduleUpdate

router = APIRouter(tags=["schedules"])


@router.get("/workspaces/{workspace_id}/schedules", response_model=list[ScheduleResponse])
async def list_schedules(
    context: WorkspaceContextDep, service: ScheduleServiceDep
) -> list[ScheduleResponse]:
    return await service.list(context.id)


@router.post(
    "/workspaces/{workspace_id}/schedules",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    payload: ScheduleCreate,
    context: WorkspaceContextDep,
    service: ScheduleServiceDep,
) -> ScheduleResponse:
    return await service.create(
        payload,
        workspace_id=context.id,
        user_id=context.user.id,
        org_id=context.user.org_id,
    )


@router.patch("/workspaces/{workspace_id}/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    context: WorkspaceContextDep,
    service: ScheduleServiceDep,
) -> ScheduleResponse:
    return await service.update(
        schedule_id,
        payload,
        workspace_id=context.id,
        user_id=context.user.id,
        org_id=context.user.org_id,
    )


@router.delete(
    "/workspaces/{workspace_id}/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ScheduleServiceDep,
) -> Response:
    await service.delete(schedule_id, context.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
