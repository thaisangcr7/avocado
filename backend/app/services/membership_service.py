"""Role resolution — the single source of truth for "may this user do this?".

Every authorisation question in the application reduces to one of two forms:

  * does this user hold at least role R **in team T**?
  * does this user hold at least role R **anywhere in org O**?

The second exists because `org_admin` is an organization-wide role that happens
to be recorded on a team membership row. An org admin can administer a team
they are not a member of; checking only their membership in *that* team would
wrongly refuse them.
"""

from __future__ import annotations

import uuid

from app.core.errors import NotFoundError, PermissionDeniedError
from app.models.enums import Role
from app.models.tenancy import Team, TeamMembership
from app.repositories.tenancy import (
    MembershipRepository,
    TeamRepository,
    UserRepository,
)


class MembershipService:
    def __init__(
        self,
        *,
        memberships: MembershipRepository,
        teams: TeamRepository,
        users: UserRepository,
    ) -> None:
        self._memberships = memberships
        self._teams = teams
        self._users = users

    async def highest_role(self, user_id: uuid.UUID) -> Role | None:
        """The strongest role this user holds anywhere in their organization."""
        rows = await self._memberships.list_for_user(user_id)
        if not rows:
            return None
        return max((m.role for m in rows), key=lambda r: r.rank)

    async def is_org_admin(self, user_id: uuid.UUID) -> bool:
        role = await self.highest_role(user_id)
        return role is not None and role.at_least(Role.ORG_ADMIN)

    async def role_in_team(self, user_id: uuid.UUID, team_id: uuid.UUID) -> Role | None:
        """This user's effective role in one team.

        The strongest applicable role: their membership in the team, their
        org-wide standing, or whichever of the two is higher. An org admin is
        an admin of every team **in their own organization**, whether or not
        they hold a membership row for it.

        That organization check is load-bearing. Without it, being an admin of
        any organization would confer admin rights on every team in every
        organization — the shortcut is what makes the role useful, and the
        scope is what stops it being a cross-tenant escalation. It is resolved
        here rather than passed in by callers, so no call site can forget it.
        """
        team = await self._teams.get(team_id)
        if team is None:
            return None

        # Nothing outside the caller's own organization is reachable, whatever
        # roles they hold elsewhere.
        user = await self._users.get(user_id)
        if user is None or user.org_id != team.org_id:
            return None

        applicable: list[Role] = []
        membership = await self._memberships.get_for_user_and_team(user_id, team_id)
        if membership is not None:
            applicable.append(membership.role)
        if await self.is_org_admin(user_id):
            applicable.append(Role.ORG_ADMIN)

        # The strongest applicable role wins, rather than the membership row
        # taking precedence. An org admin who is also recorded as a plain
        # member of some team must not lose their org-wide standing there.
        return max(applicable, key=lambda role: role.rank) if applicable else None

    async def require_team_role(
        self, user_id: uuid.UUID, team_id: uuid.UUID, minimum: Role
    ) -> tuple[Team, Role]:
        """Resolve a team the user may act on at `minimum`, or refuse.

        A team in another organization reads as 404 rather than 403 —
        confirming that an id exists is itself information an outsider should
        not get. A team the user *can* see but lacks the role for is a 403,
        which is actionable: ask an admin.
        """
        team = await self._teams.get(team_id)
        role = await self.role_in_team(user_id, team_id)

        if team is None or role is None:
            raise NotFoundError("Team not found.")
        if not role.at_least(minimum):
            raise PermissionDeniedError(
                f"This action requires the '{minimum.value}' role; you have " f"'{role.value}'."
            )
        return team, role

    async def require_org_role(self, user_id: uuid.UUID, minimum: Role) -> Role:
        role = await self.highest_role(user_id)
        if role is None:
            raise PermissionDeniedError("You do not belong to a team.")
        if not role.at_least(minimum):
            raise PermissionDeniedError(
                f"This action requires the '{minimum.value}' role; you have " f"'{role.value}'."
            )
        return role

    async def count_org_admins(self, org_id: uuid.UUID) -> int:
        return await self._memberships.count_role_in_org(org_id, Role.ORG_ADMIN)

    async def add_member(
        self, *, team_id: uuid.UUID, user_id: uuid.UUID, role: Role
    ) -> TeamMembership:
        existing = await self._memberships.get_for_user_and_team(user_id, team_id)
        if existing is not None:
            # Re-adding is treated as a role update rather than an error: it is
            # what the caller meant, and a duplicate row is impossible anyway.
            existing.role = role
            return existing
        return await self._memberships.add(
            TeamMembership(team_id=team_id, user_id=user_id, role=role)
        )
