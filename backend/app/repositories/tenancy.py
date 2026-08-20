"""Organization, user, team, membership and workspace data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.enums import Role
from app.models.tenancy import Organization, Team, TeamMembership, User, Workspace
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        return (await self._session.execute(stmt)).scalar_one_or_none()


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str, org_id: uuid.UUID | None = None) -> User | None:
        # Emails are compared case-insensitively: addresses are stored as the
        # user typed them, but nobody expects Sang@x.com and sang@x.com to be
        # different accounts.
        stmt = select(User).where(func.lower(User.email) == email.lower())
        if org_id is not None:
            stmt = stmt.where(User.org_id == org_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_with_memberships(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id).options(selectinload(User.memberships))
        return (await self._session.execute(stmt)).scalar_one_or_none()


class TeamRepository(BaseRepository[Team]):
    model = Team

    async def list_for_org(self, org_id: uuid.UUID) -> list[Team]:
        stmt = select(Team).where(Team.org_id == org_id).order_by(Team.name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_user(self, user_id: uuid.UUID) -> list[Team]:
        """Teams the user actually belongs to."""
        stmt = (
            select(Team)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(TeamMembership.user_id == user_id)
            .order_by(Team.name)
        )
        return list((await self._session.execute(stmt)).scalars().unique().all())

    async def get_by_name(self, org_id: uuid.UUID, name: str) -> Team | None:
        stmt = select(Team).where(Team.org_id == org_id, Team.name == name)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_workspaces(self, team_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Workspace).where(Workspace.team_id == team_id)
        return (await self._session.execute(stmt)).scalar_one()


class MembershipRepository(BaseRepository[TeamMembership]):
    model = TeamMembership

    async def get_for_user_and_team(
        self, user_id: uuid.UUID, team_id: uuid.UUID
    ) -> TeamMembership | None:
        stmt = select(TeamMembership).where(
            TeamMembership.user_id == user_id,
            TeamMembership.team_id == team_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[TeamMembership]:
        stmt = select(TeamMembership).where(TeamMembership.user_id == user_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_team(self, team_id: uuid.UUID) -> list[tuple[TeamMembership, User]]:
        """Members of a team with their user rows, in one query.

        Joined rather than fetched per membership: a member list is rendered
        with names and emails, and N+1 lookups for it is the classic way a
        cheap page becomes slow.
        """
        stmt = (
            select(TeamMembership, User)
            .join(User, User.id == TeamMembership.user_id)
            .where(TeamMembership.team_id == team_id)
            .order_by(User.email)
        )
        return [tuple(row) for row in (await self._session.execute(stmt)).all()]

    async def count_for_team(self, team_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(TeamMembership)
            .where(TeamMembership.team_id == team_id)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def count_role_in_org(self, org_id: uuid.UUID, role: Role) -> int:
        """How many people hold a role across the whole organization.

        Used to refuse removing or demoting the last org admin, which would
        leave the organization unadministrable.
        """
        stmt = (
            select(func.count(func.distinct(TeamMembership.user_id)))
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.org_id == org_id, TeamMembership.role == role)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def list_org_members(self, org_id: uuid.UUID) -> list[tuple[TeamMembership, User]]:
        stmt = (
            select(TeamMembership, User)
            .join(User, User.id == TeamMembership.user_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(Team.org_id == org_id)
            .order_by(User.email)
        )
        return [tuple(row) for row in (await self._session.execute(stmt)).all()]


class WorkspaceRepository(BaseRepository[Workspace]):
    model = Workspace

    async def get_for_user(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Workspace | None:
        """Fetch a workspace only if this user's team membership grants access.

        The join to `team_memberships` is the access check. Doing it here
        rather than as a follow-up query means there is no window in which a
        workspace is loaded before the caller's right to see it is established.
        """
        stmt = (
            select(Workspace)
            .join(Team, Team.id == Workspace.team_id)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(
                Workspace.id == workspace_id,
                TeamMembership.user_id == user_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Workspace]:
        stmt = (
            select(Workspace)
            .join(Team, Team.id == Workspace.team_id)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(TeamMembership.user_id == user_id)
            .order_by(Workspace.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().unique().all())

    async def get_team_id(self, workspace_id: uuid.UUID) -> uuid.UUID | None:
        stmt = select(Workspace.team_id).where(Workspace.id == workspace_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()
