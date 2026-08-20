"""Invitation routes.

Preview and accept are reachable without authentication, because the person
being invited may not have an account yet. Everything else requires being an
admin of the team in question.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import CurrentUserDep, InvitationServiceDep, SettingsDep, UsersDep
from app.core.security import decode_token
from app.models.tenancy import User
from app.schemas.auth import TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.tenancy import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationPreview,
    InvitationResponse,
)

router = APIRouter(tags=["invitations"])

_optional_bearer = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    users: UsersDep,
    settings: SettingsDep,
) -> User | None:
    """The caller, if there is one.

    Accepting an invitation has to work both for someone already signed in and
    for someone who has no account yet, so a missing or unusable token is not
    an error here — it just means "nobody".
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_token(
            settings=settings, token=credentials.credentials, expected_type="access"
        )
        user = await users.get(uuid.UUID(payload["sub"]))
    except Exception:
        return None
    return user if user is not None and user.is_active else None


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


@router.post(
    "/teams/{team_id}/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    team_id: uuid.UUID,
    payload: InvitationCreate,
    user: CurrentUserDep,
    service: InvitationServiceDep,
) -> InvitationCreatedResponse:
    """Invite someone to a team.

    The response carries the raw token exactly once — only its hash is stored,
    so there is no way to retrieve the link later. Losing it means issuing a
    new invitation.
    """
    return await service.create(
        team_id=team_id, actor_id=user.id, org_id=user.org_id, payload=payload
    )


@router.get("/teams/{team_id}/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    team_id: uuid.UUID, user: CurrentUserDep, service: InvitationServiceDep
) -> list[InvitationResponse]:
    return await service.list_for_team(team_id, user.id)


@router.delete("/invitations/{invitation_id}", response_model=MessageResponse)
async def revoke_invitation(
    invitation_id: uuid.UUID, user: CurrentUserDep, service: InvitationServiceDep
) -> MessageResponse:
    await service.revoke(invitation_id, user.id, user.org_id)
    return MessageResponse(message="Invitation revoked.")


@router.get("/invitations/{token}", response_model=InvitationPreview)
async def preview_invitation(token: str, service: InvitationServiceDep) -> InvitationPreview:
    """What the invitation offers, before signing in or signing up."""
    return await service.preview(token)


@router.post("/invitations/{token}/accept", response_model=TokenResponse)
async def accept_invitation(
    token: str,
    payload: InvitationAccept,
    user: OptionalUserDep,
    service: InvitationServiceDep,
) -> TokenResponse:
    """Join the team. Returns a session, so a new account is signed in at once."""
    return await service.accept(token=token, payload=payload, current_user=user)
