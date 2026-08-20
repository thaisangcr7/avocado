"""Teams and their membership."""

from __future__ import annotations

import uuid

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.logging import get_logger
from app.models.enums import Role
from app.models.tenancy import Team
from app.repositories.tenancy import (
    MembershipRepository,
    OrganizationRepository,
    TeamRepository,
    UserRepository,
)
from app.schemas.tenancy import (
    MemberResponse,
    OrganizationResponse,
    OrganizationUpdate,
    TeamCreate,
    TeamDetailResponse,
    TeamResponse,
    TeamUpdate,
)
from app.services.membership_service import MembershipService

log = get_logger(__name__)


class TeamService:
    def __init__(
        self,
        *,
        teams: TeamRepository,
        memberships: MembershipRepository,
        users: UserRepository,
        organizations: OrganizationRepository,
        membership_service: MembershipService,
    ) -> None:
        self._teams = teams
        self._memberships = memberships
        self._users = users
        self._organizations = organizations
        self._access = membership_service

    # --- organization ------------------------------------------------------

    async def get_organization(self, org_id: uuid.UUID) -> OrganizationResponse:
        organization = await self._organizations.get(org_id)
        if organization is None:
            raise NotFoundError("Organization not found.")
        return OrganizationResponse.model_validate(organization)

    async def update_organization(
        self, org_id: uuid.UUID, user_id: uuid.UUID, payload: OrganizationUpdate
    ) -> OrganizationResponse:
        await self._access.require_org_role(user_id, Role.ORG_ADMIN)
        organization = await self._organizations.get(org_id)
        if organization is None:
            raise NotFoundError("Organization not found.")

        organization.name = payload.name
        await self._organizations.commit()
        await self._organizations.refresh(organization)
        return OrganizationResponse.model_validate(organization)

    async def list_org_members(self, org_id: uuid.UUID, user_id: uuid.UUID) -> list[MemberResponse]:
        await self._access.require_org_role(user_id, Role.MEMBER)
        rows = await self._memberships.list_org_members(org_id)

        # One person can sit on several teams; the directory shows each person
        # once, at their strongest role.
        best: dict[uuid.UUID, MemberResponse] = {}
        for membership, user in rows:
            existing = best.get(user.id)
            if existing is None or membership.role.rank > existing.role.rank:
                best[user.id] = MemberResponse(
                    user_id=user.id,
                    email=user.email,
                    full_name=user.full_name,
                    role=membership.role,
                    is_active=user.is_active,
                    joined_at=membership.created_at,
                )
        return sorted(best.values(), key=lambda m: m.email)

    # --- teams -------------------------------------------------------------

    async def list_teams(self, org_id: uuid.UUID, user_id: uuid.UUID) -> list[TeamResponse]:
        """Teams the caller can see.

        An org admin sees every team; everyone else sees only their own. That
        is the difference between administering an organization and working in
        it.
        """
        teams = (
            await self._teams.list_for_org(org_id)
            if await self._access.is_org_admin(user_id)
            else await self._teams.list_for_user(user_id)
        )
        return [TeamResponse.model_validate(t) for t in teams]

    async def create_team(
        self, org_id: uuid.UUID, user_id: uuid.UUID, payload: TeamCreate
    ) -> TeamDetailResponse:
        await self._access.require_org_role(user_id, Role.ORG_ADMIN)

        if await self._teams.get_by_name(org_id, payload.name):
            raise ConflictError(f"A team named '{payload.name}' already exists.")

        team = await self._teams.add(
            Team(org_id=org_id, name=payload.name, description=payload.description)
        )
        await self._teams.commit()

        # The creator joins as an admin — a team nobody can administer is not
        # useful, and they are an org admin regardless.
        await self._access.add_member(team_id=team.id, user_id=user_id, role=Role.TEAM_ADMIN)
        await self._teams.commit()

        log.info("team_created", team_id=str(team.id), org_id=str(org_id))
        return await self.get_team(team.id, user_id)

    async def get_team(self, team_id: uuid.UUID, user_id: uuid.UUID) -> TeamDetailResponse:
        team, role = await self._access.require_team_role(user_id, team_id, Role.VIEWER)
        return TeamDetailResponse(
            id=team.id,
            org_id=team.org_id,
            name=team.name,
            description=team.description,
            created_at=team.created_at,
            member_count=await self._memberships.count_for_team(team_id),
            workspace_count=await self._teams.count_workspaces(team_id),
            your_role=role,
        )

    async def update_team(
        self, team_id: uuid.UUID, user_id: uuid.UUID, payload: TeamUpdate
    ) -> TeamDetailResponse:
        team, _ = await self._access.require_team_role(user_id, team_id, Role.TEAM_ADMIN)

        updates = payload.model_dump(exclude_unset=True)
        renaming = "name" in updates and updates["name"] != team.name
        if renaming and await self._teams.get_by_name(team.org_id, updates["name"]):
            raise ConflictError(f"A team named '{updates['name']}' already exists.")
        for field, value in updates.items():
            setattr(team, field, value)

        await self._teams.commit()
        await self._teams.refresh(team)
        return await self.get_team(team_id, user_id)

    async def delete_team(self, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
        team, _ = await self._access.require_team_role(user_id, team_id, Role.ORG_ADMIN)

        # Deleting a team cascades to its workspaces, and with them every
        # document, conversation and analysis run inside. That is a lot of work
        # to destroy by accident, so it is refused while any workspace remains.
        workspaces = await self._teams.count_workspaces(team_id)
        if workspaces > 0:
            raise ConflictError(
                f"This team still has {workspaces} workspace"
                f"{'s' if workspaces != 1 else ''}. Delete them first."
            )

        await self._teams.delete(team)
        await self._teams.commit()
        log.info("team_deleted", team_id=str(team_id))

    # --- members -----------------------------------------------------------

    async def list_members(self, team_id: uuid.UUID, user_id: uuid.UUID) -> list[MemberResponse]:
        await self._access.require_team_role(user_id, team_id, Role.VIEWER)
        return [
            MemberResponse(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=membership.role,
                is_active=user.is_active,
                joined_at=membership.created_at,
            )
            for membership, user in await self._memberships.list_for_team(team_id)
        ]

    async def set_member_role(
        self,
        *,
        team_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        role: Role,
    ) -> MemberResponse:
        _team, actor_role = await self._access.require_team_role(actor_id, team_id, Role.TEAM_ADMIN)

        # Nobody may grant a role above their own — otherwise a team admin
        # could make themselves an org admin, and the hierarchy means nothing.
        if role.rank > actor_role.rank:
            raise PermissionDeniedError(
                f"You cannot grant '{role.value}', which is above your own "
                f"'{actor_role.value}'."
            )

        membership = await self._memberships.get_for_user_and_team(target_user_id, team_id)
        if membership is None:
            raise NotFoundError("That person is not a member of this team.")

        await self._guard_last_org_admin(org_id=org_id, current_role=membership.role, new_role=role)

        membership.role = role
        await self._memberships.commit()

        user = await self._users.get(target_user_id)
        if user is None:
            raise NotFoundError("User not found.")

        log.info(
            "member_role_changed",
            team_id=str(team_id),
            user_id=str(target_user_id),
            role=role.value,
        )
        return MemberResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=role,
            is_active=user.is_active,
            joined_at=membership.created_at,
        )

    async def remove_member(
        self,
        *,
        team_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> None:
        # Leaving a team yourself needs no privilege; removing someone else does.
        if target_user_id != actor_id:
            await self._access.require_team_role(actor_id, team_id, Role.TEAM_ADMIN)

        membership = await self._memberships.get_for_user_and_team(target_user_id, team_id)
        if membership is None:
            raise NotFoundError("That person is not a member of this team.")

        await self._guard_last_org_admin(org_id=org_id, current_role=membership.role, new_role=None)

        await self._memberships.delete(membership)
        await self._memberships.commit()
        log.info("member_removed", team_id=str(team_id), user_id=str(target_user_id))

    async def _guard_last_org_admin(
        self,
        *,
        org_id: uuid.UUID,
        current_role: Role,
        new_role: Role | None,
    ) -> None:
        """Refuse a change that would leave the organization with no admin.

        An organization nobody can administer cannot invite, cannot promote,
        and cannot recover — it is bricked. Cheap to prevent, impossible to fix
        from inside afterwards.
        """
        if current_role is not Role.ORG_ADMIN:
            return
        if new_role is not None and new_role is Role.ORG_ADMIN:
            return

        # Count distinct people, not membership rows: one admin sitting on
        # three teams is still one admin.
        if await self._access.count_org_admins(org_id) <= 1:
            raise ValidationError(
                "This is the organization's only administrator. Promote someone "
                "else before removing or demoting them."
            )
