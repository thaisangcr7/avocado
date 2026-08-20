"""Project, task, suggestion and knowledge routes.

Task visibility (§11) is applied in the repository, so these handlers pass the
caller's identity down and never filter anything themselves.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    KnowledgeServiceDep,
    ProjectServiceDep,
    SuggestionServiceDep,
    TaskResumeServiceDep,
    WorkspaceContextDep,
)
from app.models.enums import DocumentKind, ProjectStatus, TaskStatus
from app.schemas.common import MessageResponse
from app.schemas.projects import (
    ClassificationResponse,
    KnowledgeMapResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdate,
    SuggestionsResponse,
    TaskCreate,
    TaskResponse,
    TaskResumeResponse,
    TaskUpdate,
)

router = APIRouter(tags=["projects"])


# --- projects --------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectResponse])
async def list_projects(
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
) -> list[ProjectResponse]:
    """Projects the caller can see.

    A restricted project appears only to its members, its creator, and anyone
    holding a task in it — plus team admins.
    """
    return await service.list_projects(
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        status=status_filter,
    )


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    payload: ProjectCreate, context: WorkspaceContextDep, service: ProjectServiceDep
) -> ProjectDetailResponse:
    return await service.create_project(
        workspace_id=context.id, user_id=context.user.id, payload=payload
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}",
    response_model=ProjectDetailResponse,
)
async def get_project(
    project_id: uuid.UUID, context: WorkspaceContextDep, service: ProjectServiceDep
) -> ProjectDetailResponse:
    return await service.get_project(
        project_id=project_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
    )


@router.patch(
    "/workspaces/{workspace_id}/projects/{project_id}",
    response_model=ProjectDetailResponse,
)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
) -> ProjectDetailResponse:
    return await service.update_project(
        project_id=project_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        payload=payload,
    )


@router.delete("/workspaces/{workspace_id}/projects/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: uuid.UUID, context: WorkspaceContextDep, service: ProjectServiceDep
) -> MessageResponse:
    await service.delete_project(
        project_id=project_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
    )
    return MessageResponse(message="Project deleted.")


@router.put(
    "/workspaces/{workspace_id}/projects/{project_id}/members/{member_id}",
    response_model=MessageResponse,
)
async def add_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
) -> MessageResponse:
    await service.add_member(
        project_id=project_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        member_id=member_id,
    )
    return MessageResponse(message="Member added.")


@router.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/members/{member_id}",
    response_model=MessageResponse,
)
async def remove_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
) -> MessageResponse:
    await service.remove_member(
        project_id=project_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        member_id=member_id,
    )
    return MessageResponse(message="Member removed.")


# --- tasks -----------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> list[TaskResponse]:
    """Tasks the caller can see, soonest deadline first."""
    return await service.list_tasks(
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        project_id=project_id,
        assignee_id=assignee_id,
        status=status_filter,
    )


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
) -> TaskResponse:
    return await service.create_task(
        project_id=project_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        payload=payload,
    )


@router.get("/workspaces/{workspace_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID, context: WorkspaceContextDep, service: ProjectServiceDep
) -> TaskResponse:
    return await service.get_task(
        task_id=task_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
    )


@router.patch("/workspaces/{workspace_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    context: WorkspaceContextDep,
    service: ProjectServiceDep,
) -> TaskResponse:
    return await service.update_task(
        task_id=task_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        payload=payload,
    )


@router.delete("/workspaces/{workspace_id}/tasks/{task_id}", response_model=MessageResponse)
async def delete_task(
    task_id: uuid.UUID, context: WorkspaceContextDep, service: ProjectServiceDep
) -> MessageResponse:
    await service.delete_task(
        task_id=task_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
    )
    return MessageResponse(message="Task deleted.")


@router.get(
    "/workspaces/{workspace_id}/tasks/{task_id}/resume",
    response_model=TaskResumeResponse,
)
async def resume_task(
    task_id: uuid.UUID, context: WorkspaceContextDep, service: TaskResumeServiceDep
) -> TaskResumeResponse:
    """Pick a task back up.

    Returns the task's own thread plus a synthesis of where things stood, so
    coming back after two days on something else does not start from a blank
    chat. `synthesized` is false when the summary is the deterministic
    fallback rather than model-written.
    """
    return await service.resume(
        task_id=task_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        user_id=context.user.id,
        preferred_model=context.preferred_model,
    )


# --- suggestions -----------------------------------------------------------


@router.get("/workspaces/{workspace_id}/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(
    context: WorkspaceContextDep,
    service: SuggestionServiceDep,
    refresh: bool = False,
) -> SuggestionsResponse:
    """The caller's proactive nudges.

    A digest, not a record: nothing here is persisted, and the response is
    cached briefly so opening several tabs does not recompute it each time.
    """
    return await service.suggestions(
        workspace_id=context.id,
        user_id=context.user.id,
        preferred_model=context.preferred_model,
        refresh=refresh,
    )


# --- org knowledge ---------------------------------------------------------


@router.get("/workspaces/{workspace_id}/knowledge", response_model=KnowledgeMapResponse)
async def knowledge_map(
    context: WorkspaceContextDep,
    service: KnowledgeServiceDep,
    kind: DocumentKind | None = None,
    topic: str | None = None,
    team_id: uuid.UUID | None = None,
) -> KnowledgeMapResponse:
    """What this team does, derived from what it has uploaded."""
    return await service.map(workspace_id=context.id, kind=kind, team_id=team_id, topic=topic)


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}/classification",
    response_model=ClassificationResponse,
)
async def get_classification(
    document_id: uuid.UUID, context: WorkspaceContextDep, service: KnowledgeServiceDep
) -> ClassificationResponse:
    return await service.get_for_document(document_id, context.id)


@router.post(
    "/workspaces/{workspace_id}/documents/{document_id}/classification",
    response_model=ClassificationResponse,
)
async def classify_document(
    document_id: uuid.UUID, context: WorkspaceContextDep, service: KnowledgeServiceDep
) -> ClassificationResponse:
    """Classify or reclassify a document, bumping its version."""
    result = await service.classify_document(
        document_id=document_id,
        workspace_id=context.id,
        team_id=context.workspace.team_id,
        preferred_model=context.preferred_model,
    )
    if result is None:
        from app.core.errors import ProviderError

        raise ProviderError("This document could not be classified.")
    return result
