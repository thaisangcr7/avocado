"""Organization, team and membership routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, TeamServiceDep
from app.schemas.common import MessageResponse
from app.schemas.tenancy import (
    MemberResponse,
    MemberRoleUpdate,
    OrganizationResponse,
    OrganizationUpdate,
    TeamCreate,
    TeamDetailResponse,
    TeamResponse,
    TeamUpdate,
)

router = APIRouter(tags=["teams"])


# --- organization ----------------------------------------------------------


@router.get("/organizations/current", response_model=OrganizationResponse)
async def get_current_organization(
    user: CurrentUserDep, service: TeamServiceDep
) -> OrganizationResponse:
    """The caller's organization.

    Addressed as `current` rather than by id: a user belongs to exactly one
    organization, so an id in the path would only be an opportunity to pass
    the wrong one.
    """
    return await service.get_organization(user.org_id)


@router.patch("/organizations/current", response_model=OrganizationResponse)
async def update_current_organization(
    payload: OrganizationUpdate, user: CurrentUserDep, service: TeamServiceDep
) -> OrganizationResponse:
    return await service.update_organization(user.org_id, user.id, payload)


@router.get("/organizations/current/members", response_model=list[MemberResponse])
async def list_organization_members(
    user: CurrentUserDep, service: TeamServiceDep
) -> list[MemberResponse]:
    """Everyone in the organization, each at their strongest role."""
    return await service.list_org_members(user.org_id, user.id)


# --- teams -----------------------------------------------------------------


@router.get("/teams", response_model=list[TeamResponse])
async def list_teams(user: CurrentUserDep, service: TeamServiceDep) -> list[TeamResponse]:
    """Teams the caller can see — all of them for an org admin, their own
    otherwise."""
    return await service.list_teams(user.org_id, user.id)


@router.post("/teams", response_model=TeamDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate, user: CurrentUserDep, service: TeamServiceDep
) -> TeamDetailResponse:
    return await service.create_team(user.org_id, user.id, payload)


@router.get("/teams/{team_id}", response_model=TeamDetailResponse)
async def get_team(
    team_id: uuid.UUID, user: CurrentUserDep, service: TeamServiceDep
) -> TeamDetailResponse:
    return await service.get_team(team_id, user.id)


@router.patch("/teams/{team_id}", response_model=TeamDetailResponse)
async def update_team(
    team_id: uuid.UUID,
    payload: TeamUpdate,
    user: CurrentUserDep,
    service: TeamServiceDep,
) -> TeamDetailResponse:
    return await service.update_team(team_id, user.id, payload)


@router.delete("/teams/{team_id}", response_model=MessageResponse)
async def delete_team(
    team_id: uuid.UUID, user: CurrentUserDep, service: TeamServiceDep
) -> MessageResponse:
    await service.delete_team(team_id, user.id)
    return MessageResponse(message="Team deleted.")


# --- members ---------------------------------------------------------------


@router.get("/teams/{team_id}/members", response_model=list[MemberResponse])
async def list_team_members(
    team_id: uuid.UUID, user: CurrentUserDep, service: TeamServiceDep
) -> list[MemberResponse]:
    return await service.list_members(team_id, user.id)


@router.patch("/teams/{team_id}/members/{member_id}", response_model=MemberResponse)
async def set_member_role(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: MemberRoleUpdate,
    user: CurrentUserDep,
    service: TeamServiceDep,
) -> MemberResponse:
    """Change someone's role. Nobody may grant a role above their own."""
    return await service.set_member_role(
        team_id=team_id,
        target_user_id=member_id,
        actor_id=user.id,
        org_id=user.org_id,
        role=payload.role,
    )


@router.delete("/teams/{team_id}/members/{member_id}", response_model=MessageResponse)
async def remove_member(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    user: CurrentUserDep,
    service: TeamServiceDep,
) -> MessageResponse:
    """Remove someone, or leave the team yourself."""
    await service.remove_member(
        team_id=team_id,
        target_user_id=member_id,
        actor_id=user.id,
        org_id=user.org_id,
    )
    return MessageResponse(
        message="You have left the team." if member_id == user.id else "Member removed."
    )
