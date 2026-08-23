"""Preset routes — the prompt library.

Org-scoped rather than workspace-scoped, so these hang off the authenticated
user's organisation rather than a workspace in the path. The user's `org_id`
comes from their record, never from the request, which is what stops a preset
being read into or written out of another tenant.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUserDep, PresetServiceDep
from app.repositories.presets import PresetFilter
from app.schemas.presets import (
    PresetCreate,
    PresetListResponse,
    PresetResponse,
    PresetShareRequest,
    PresetUpdate,
)

router = APIRouter(tags=["presets"], prefix="/presets")


@router.get("", response_model=PresetListResponse)
async def list_presets(
    user: CurrentUserDep,
    service: PresetServiceDep,
    which: PresetFilter = Query(default="all", description="Which tab of the library."),
    search: str | None = Query(default=None, max_length=200),
) -> PresetListResponse:
    """Everything this person may see, narrowed by tab and search."""
    return await service.list(user_id=user.id, org_id=user.org_id, which=which, search=search)


@router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(
    payload: PresetCreate,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    return await service.create(payload, user_id=user.id, org_id=user.org_id)


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: uuid.UUID,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    return await service.get(preset_id, user_id=user.id, org_id=user.org_id)


@router.patch("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: uuid.UUID,
    payload: PresetUpdate,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    return await service.update(preset_id, payload, user_id=user.id, org_id=user.org_id)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: uuid.UUID,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> Response:
    await service.delete(preset_id, user_id=user.id, org_id=user.org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{preset_id}/pin", response_model=PresetResponse)
async def pin_preset(
    preset_id: uuid.UUID,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    return await service.set_pinned(preset_id, pinned=True, user_id=user.id, org_id=user.org_id)


@router.delete("/{preset_id}/pin", response_model=PresetResponse)
async def unpin_preset(
    preset_id: uuid.UUID,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    return await service.set_pinned(preset_id, pinned=False, user_id=user.id, org_id=user.org_id)


@router.post("/{preset_id}/share", response_model=PresetResponse)
async def share_preset(
    preset_id: uuid.UUID,
    payload: PresetShareRequest,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    return await service.share(
        preset_id, recipient_id=payload.user_id, user_id=user.id, org_id=user.org_id
    )


@router.post("/{preset_id}/publish", response_model=PresetResponse)
async def publish_preset(
    preset_id: uuid.UUID,
    user: CurrentUserDep,
    service: PresetServiceDep,
) -> PresetResponse:
    """Offer a preset to the whole organisation."""
    return await service.publish(preset_id, user_id=user.id, org_id=user.org_id)
