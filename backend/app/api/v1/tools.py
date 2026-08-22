"""Tool registry routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import ToolServiceDep, WorkspaceContextDep
from app.schemas.tools import ToolSelectionResponse, ToolSelectionUpdate

router = APIRouter(tags=["tools"])


@router.get(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/tools",
    response_model=ToolSelectionResponse,
)
async def list_tools(
    conversation_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ToolServiceDep,
) -> ToolSelectionResponse:
    """Every tool, which are on for this conversation, and what that costs."""
    return await service.catalogue(
        conversation_id, context.workspace.id, preferred_model=context.preferred_model
    )


@router.put(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/tools",
    response_model=ToolSelectionResponse,
)
async def set_tools(
    conversation_id: uuid.UUID,
    payload: ToolSelectionUpdate,
    context: WorkspaceContextDep,
    service: ToolServiceDep,
) -> ToolSelectionResponse:
    """Replace the enabled set. A tool that is not connected is refused."""
    return await service.set_enabled(
        conversation_id=conversation_id,
        workspace_id=context.workspace.id,
        slugs=payload.slugs,
        preferred_model=context.preferred_model,
    )
