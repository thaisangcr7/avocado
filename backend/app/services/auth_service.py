"""Registration, login, and token refresh.

Registration creates the whole tenant spine in one transaction — organization,
user, default team, membership, default workspace — because a user with no team
has nowhere to put anything, and a half-provisioned account is worse than a
failed one.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.enums import Role
from app.models.tenancy import Organization, Team, TeamMembership, User, Workspace
from app.repositories.tenancy import (
    MembershipRepository,
    OrganizationRepository,
    TeamRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)

log = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug[:80] or "org"


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        users: UserRepository,
        organizations: OrganizationRepository,
        teams: TeamRepository,
        memberships: MembershipRepository,
        workspaces: WorkspaceRepository,
    ) -> None:
        self._settings = settings
        self._users = users
        self._organizations = organizations
        self._teams = teams
        self._memberships = memberships
        self._workspaces = workspaces

    async def register(self, payload: RegisterRequest) -> TokenResponse:
        existing = await self._users.get_by_email(payload.email)
        if existing is not None:
            # Registration is an unauthenticated endpoint, so a distinct
            # "already exists" here is an email-enumeration oracle. It is
            # accepted deliberately: the alternative (silently succeeding) is
            # far more confusing, and the same fact is observable from the
            # login form anyway.
            raise ConflictError("An account with that email already exists.")

        slug = _slugify(payload.organization_name)
        if await self._organizations.get_by_slug(slug):
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        organization = await self._organizations.add(
            Organization(name=payload.organization_name, slug=slug)
        )
        user = await self._users.add(
            User(
                org_id=organization.id,
                email=payload.email,
                full_name=payload.full_name,
                password_hash=hash_password(payload.password),
                auth_provider="local",
            )
        )
        team = await self._teams.add(
            Team(org_id=organization.id, name="General", description="Default team")
        )
        # The creator is the org admin — there is nobody else to be.
        await self._memberships.add(
            TeamMembership(team_id=team.id, user_id=user.id, role=Role.ORG_ADMIN)
        )
        await self._workspaces.add(
            Workspace(
                team_id=team.id,
                name="My Workspace",
                description="Default workspace",
            )
        )
        await self._users.commit()

        log.info("user_registered", user_id=str(user.id), org_id=str(organization.id))
        return self._issue_tokens(user)

    async def login(self, payload: LoginRequest) -> TokenResponse:
        user = await self._users.get_by_email(payload.email)

        # Verify against a dummy hash when the user does not exist, so a
        # missing account and a wrong password take the same time. Argon2 is
        # slow by design, which makes the difference otherwise measurable.
        stored = user.password_hash if user and user.password_hash else _DUMMY_HASH
        password_ok = verify_password(payload.password, stored)

        if user is None or not user.password_hash or not password_ok:
            raise AuthenticationError("Incorrect email or password.")
        if not user.is_active:
            raise AuthenticationError("This account is disabled.")

        # Transparently upgrade a hash left behind by older argon2 parameters.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(payload.password)
            await self._users.commit()

        log.info("user_logged_in", user_id=str(user.id))
        return self._issue_tokens(user)

    async def demo_session(self) -> TokenResponse:
        if not self._settings.public_demo_enabled:
            raise NotFoundError("Not found.")

        email, password = self._resolve_demo_credentials()
        return await self.login(LoginRequest(email=email, password=password))

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(
            settings=self._settings, token=refresh_token, expected_type="refresh"
        )
        user = await self._users.get(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid token.")
        return self._issue_tokens(user)

    async def current_user(self, user_id: uuid.UUID) -> CurrentUserResponse:
        user = await self._users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        organization = await self._organizations.get(user.org_id)
        workspaces = await self._workspaces.list_for_user(user.id)
        return CurrentUserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            org_id=user.org_id,
            is_active=user.is_active,
            organization_name=organization.name if organization else "",
            workspace_ids=[w.id for w in workspaces],
        )

    def _issue_tokens(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_token(
                settings=self._settings,
                subject=user.id,
                token_type="access",  # noqa: S106 - a token kind, not a secret
                org_id=user.org_id,
            ),
            refresh_token=create_token(
                settings=self._settings,
                subject=user.id,
                token_type="refresh",  # noqa: S106 - a token kind, not a secret
                org_id=user.org_id,
            ),
            expires_in=self._settings.access_token_ttl_minutes * 60,
        )

    def _resolve_demo_credentials(self) -> tuple[str, str]:
        configured_email = (self._settings.public_demo_email or "").strip()
        configured_password = (self._settings.public_demo_password or "").strip()
        if configured_email and configured_password:
            return configured_email, configured_password

        # In production the manifest fallback is refused: a public demo should
        # use explicit restricted credentials, never whatever account was
        # created first by a seed script.
        if self._settings.is_production:
            raise AuthenticationError(
                "Public demo access is not configured. Set PUBLIC_DEMO_EMAIL "
                "and PUBLIC_DEMO_PASSWORD."
            )

        manifest_path = Path(self._settings.public_demo_manifest_path)
        if not manifest_path.exists():
            raise AuthenticationError(
                "Public demo access is not configured. Seed demo data or set "
                "PUBLIC_DEMO_EMAIL/PUBLIC_DEMO_PASSWORD."
            )

        try:
            payload = json.loads(manifest_path.read_text())
            owner = payload.get("owner") or {}
            email = str(owner.get("email") or "").strip()
            password = str(owner.get("password") or "").strip()
        except Exception as exc:
            raise AuthenticationError("Public demo manifest could not be read.") from exc

        if not email or not password:
            raise AuthenticationError("Public demo manifest does not contain usable credentials.")

        return email, password


# A real argon2 hash of a value nobody can log in with — used only to keep
# login timing uniform for unknown accounts.
_DUMMY_HASH = hash_password(uuid.uuid4().hex)
