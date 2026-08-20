"""Invitations: bringing a person into a team.

The token is a capability — holding it is what grants the join — so it is
handled like a credential throughout:

* generated with a CSPRNG, never a counter or a UUID
* only its SHA-256 is stored, so a database read cannot reconstruct a link
* returned exactly once, at creation, and never written to a log
* compared by hash lookup, so there is no string comparison to time

Acceptance has two paths. An authenticated user joins directly. An unknown
address creates an account, and that path is the only way a user is ever
created outside registration — which is why the organization comes from the
*invitation*, never from the request body.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import create_token, hash_password
from app.models.enums import Role
from app.models.invitations import Invitation, InvitationStatus
from app.models.tenancy import User
from app.repositories.invitations import InvitationRepository
from app.repositories.tenancy import (
    MembershipRepository,
    OrganizationRepository,
    TeamRepository,
    UserRepository,
)
from app.schemas.auth import TokenResponse
from app.schemas.tenancy import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationPreview,
    InvitationResponse,
)
from app.services.membership_service import MembershipService

log = get_logger(__name__)

# 32 bytes of CSPRNG entropy. Long enough that guessing is not a threat model,
# short enough to survive being pasted into a chat window.
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """Hash an invitation token for storage and lookup.

    Plain SHA-256 rather than a password hash: the token is already 256 bits of
    CSPRNG output, so there is no low-entropy secret to slow an attacker down
    over, and lookup has to be a single indexed read.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class InvitationService:
    def __init__(
        self,
        *,
        settings: Settings,
        invitations: InvitationRepository,
        teams: TeamRepository,
        users: UserRepository,
        memberships: MembershipRepository,
        organizations: OrganizationRepository,
        membership_service: MembershipService,
    ) -> None:
        self._settings = settings
        self._invitations = invitations
        self._teams = teams
        self._users = users
        self._memberships = memberships
        self._organizations = organizations
        self._access = membership_service

    async def create(
        self,
        *,
        team_id: uuid.UUID,
        actor_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: InvitationCreate,
    ) -> InvitationCreatedResponse:
        team, actor_role = await self._access.require_team_role(actor_id, team_id, Role.TEAM_ADMIN)

        # Inviting someone above your own level would be privilege escalation
        # by proxy.
        if payload.role.rank > actor_role.rank:
            raise ValidationError(
                f"You cannot invite someone as '{payload.role.value}', which is "
                f"above your own '{actor_role.value}'."
            )

        email = payload.email.strip()
        existing_user = await self._users.get_by_email(email)

        if existing_user is not None:
            # An address identifies exactly one account across the system, so
            # someone already in another organization cannot be invited here.
            if existing_user.org_id != org_id:
                raise ConflictError(
                    "That address already belongs to an account in another " "organization."
                )
            if await self._memberships.get_for_user_and_team(existing_user.id, team_id):
                raise ConflictError("That person is already a member of this team.")

        if await self._invitations.find_pending(team_id, email):
            raise ConflictError(
                "An invitation is already pending for that address. Revoke it "
                "first to issue a new one."
            )

        token = secrets.token_urlsafe(TOKEN_BYTES)
        invitation = await self._invitations.add(
            Invitation(
                org_id=org_id,
                team_id=team_id,
                invited_by=actor_id,
                email=email,
                role=payload.role,
                token_hash=hash_token(token),
                status=InvitationStatus.PENDING,
                expires_at=datetime.now(UTC) + timedelta(days=payload.expires_in_days),
            )
        )
        await self._invitations.commit()

        # Deliberately logs the invitation id and team, never the token.
        log.info(
            "invitation_created",
            invitation_id=str(invitation.id),
            team_id=str(team_id),
            role=payload.role.value,
        )
        _ = team
        return InvitationCreatedResponse(
            invitation=InvitationResponse.model_validate(invitation),
            accept_url=f"{self._settings.public_web_url}/invite/{token}",
            token=token,
        )

    async def list_for_team(
        self, team_id: uuid.UUID, actor_id: uuid.UUID
    ) -> list[InvitationResponse]:
        await self._access.require_team_role(actor_id, team_id, Role.TEAM_ADMIN)
        await self._invitations.expire_stale()
        await self._invitations.commit()
        rows = await self._invitations.list_for_team(team_id, pending_only=False)
        return [InvitationResponse.model_validate(i) for i in rows]

    async def revoke(
        self, invitation_id: uuid.UUID, actor_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        invitation = await self._invitations.get_for_org(invitation_id, org_id)
        if invitation is None:
            raise NotFoundError("Invitation not found.")

        await self._access.require_team_role(actor_id, invitation.team_id, Role.TEAM_ADMIN)

        if invitation.status is not InvitationStatus.PENDING:
            raise ConflictError(f"This invitation is already {invitation.status.value}.")

        invitation.status = InvitationStatus.REVOKED
        await self._invitations.commit()
        log.info("invitation_revoked", invitation_id=str(invitation_id))

    async def preview(self, token: str) -> InvitationPreview:
        """What an invited person sees before authenticating.

        Unauthenticated by necessity — the recipient may have no account yet —
        so it returns only what is needed to decide whether to accept. A
        guessed token reveals nothing about the organization's shape.
        """
        invitation = await self._resolve_usable(token)

        team = await self._teams.get(invitation.team_id)
        organization = await self._organizations.get(invitation.org_id)
        if team is None or organization is None:
            raise NotFoundError("This invitation is no longer valid.")

        existing = await self._users.get_by_email(invitation.email)
        return InvitationPreview(
            organization_name=organization.name,
            team_name=team.name,
            email=invitation.email,
            role=invitation.role,
            expires_at=invitation.expires_at,
            requires_account=existing is None,
        )

    async def accept(
        self,
        *,
        token: str,
        payload: InvitationAccept,
        current_user: User | None,
    ) -> TokenResponse:
        """Join the team the invitation names.

        Returns a token pair either way, so a new user is signed in immediately
        rather than being invited and then asked to log in.
        """
        invitation = await self._resolve_usable(token)
        user = current_user

        if user is not None:
            # An authenticated caller may only accept an invitation addressed
            # to them; otherwise a leaked link would let anyone join.
            if user.email.lower() != invitation.email.lower():
                raise ValidationError("This invitation was sent to a different address.")
        else:
            user = await self._users.get_by_email(invitation.email)
            if user is None:
                user = await self._create_invited_user(invitation, payload)
            else:
                # The account exists but nobody is signed in. Creating a session
                # from the link alone would make the invitation a password.
                raise ValidationError(
                    "An account already exists for this address. Sign in first, "
                    "then open the invitation link again."
                )

        await self._access.add_member(
            team_id=invitation.team_id, user_id=user.id, role=invitation.role
        )

        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(UTC)
        invitation.accepted_by = user.id
        await self._invitations.commit()

        log.info(
            "invitation_accepted",
            invitation_id=str(invitation.id),
            user_id=str(user.id),
            team_id=str(invitation.team_id),
        )
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

    async def _create_invited_user(self, invitation: Invitation, payload: InvitationAccept) -> User:
        if not payload.password:
            raise ValidationError("A password is required to create your account.")

        # The organization comes from the invitation, never from the request:
        # this is the one path that creates a user outside registration, and
        # taking org_id from the body would let anyone join any organization.
        user = await self._users.add(
            User(
                org_id=invitation.org_id,
                email=invitation.email,
                full_name=payload.full_name,
                password_hash=hash_password(payload.password),
                auth_provider="local",
            )
        )
        await self._users.commit()
        log.info("invited_user_created", user_id=str(user.id), org_id=str(invitation.org_id))
        return user

    async def _resolve_usable(self, token: str) -> Invitation:
        """Find a pending, unexpired invitation, or refuse uniformly.

        Every failure — unknown, revoked, already used, elapsed — reports the
        same thing. Distinguishing them would let someone probe which tokens
        once existed.
        """
        invitation = await self._invitations.get_by_token_hash(hash_token(token))
        if invitation is None or invitation.status is not InvitationStatus.PENDING:
            raise NotFoundError("This invitation is not valid.")

        expires_at = invitation.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            invitation.status = InvitationStatus.EXPIRED
            await self._invitations.commit()
            raise NotFoundError("This invitation is not valid.")

        return invitation
