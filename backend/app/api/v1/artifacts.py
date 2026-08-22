"""Artifact routes — what the assistant produced, and its history."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ArtifactServiceDep, WorkspaceContextDep
from app.models.enums import ArtifactAuthor
from app.schemas.artifacts import (
    ArtifactAuthorRequest,
    ArtifactDetailResponse,
    ArtifactForCreate,
    ArtifactForUpdate,
    ArtifactResponse,
)

router = APIRouter(tags=["artifacts"])


@router.get("/workspaces/{workspace_id}/artifacts", response_model=list[ArtifactResponse])
async def list_artifacts(
    context: WorkspaceContextDep,
    service: ArtifactServiceDep,
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ArtifactResponse]:
    """Newest version of each artifact, most recent first.

    Filtered to one conversation when asked, which is what the in-thread panel
    shows; unfiltered it is the workspace's whole output.
    """
    return await service.list_for_workspace(context.workspace.id, conversation_id=conversation_id)


@router.post(
    "/workspaces/{workspace_id}/artifacts",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_artifact(
    payload: ArtifactForCreate,
    context: WorkspaceContextDep,
    service: ArtifactServiceDep,
) -> ArtifactResponse:
    return await service.create(
        workspace_id=context.workspace.id,
        payload=payload,
        user_id=context.user.id,
        author=ArtifactAuthor.USER,
    )


@router.post(
    "/workspaces/{workspace_id}/artifacts/generate",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_artifact(
    payload: ArtifactAuthorRequest,
    context: WorkspaceContextDep,
    service: ArtifactServiceDep,
) -> ArtifactResponse:
    """Have the model write a document and keep it as an artifact."""
    return await service.author(
        workspace_id=context.workspace.id,
        instruction=payload.instruction,
        context=payload.context,
        conversation_id=payload.conversation_id,
        user_id=context.user.id,
        preferred_model=context.preferred_model,
    )


@router.get(
    "/workspaces/{workspace_id}/artifacts/{artifact_id}",
    response_model=ArtifactDetailResponse,
)
async def get_artifact(
    artifact_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ArtifactServiceDep,
) -> ArtifactDetailResponse:
    """One version, with the full version list for the picker."""
    return await service.get(artifact_id, context.workspace.id)


@router.post(
    "/workspaces/{workspace_id}/artifacts/{artifact_id}/versions",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def revise_artifact(
    artifact_id: uuid.UUID,
    payload: ArtifactForUpdate,
    context: WorkspaceContextDep,
    service: ArtifactServiceDep,
) -> ArtifactResponse:
    """Append a new version. The previous one stays readable."""
    return await service.revise(
        artifact_id=artifact_id,
        workspace_id=context.workspace.id,
        payload=payload,
        user_id=context.user.id,
        author=ArtifactAuthor.USER,
    )


@router.get("/workspaces/{workspace_id}/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ArtifactServiceDep,
) -> Response:
    """The raw file.

    Always an attachment, never rendered by the browser at this origin. An
    artifact is model-written markup, so serving it inline would run its script
    against the user's session.
    """
    artifact = await service.get(artifact_id, context.workspace.id)
    return Response(
        content=artifact.content or "",
        media_type=service.media_type_for(artifact.kind),
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            # Belt and braces: even if the media type were ever loosened, this
            # stops a browser sniffing its way to text/html.
            "X-Content-Type-Options": "nosniff",
        },
    )
