"""Organization, team, membership and invitation resources."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Role
from app.models.invitations import InvitationStatus
from app.schemas.auth import MIN_PASSWORD_LENGTH
from app.schemas.common import ApiModel


class OrganizationResponse(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_tier: str
    monthly_budget_usd: float | None
    created_at: datetime


class OrganizationUpdate(BaseModel):
    """Both fields optional so either can be changed without restating the other.

    `monthly_budget_usd` is explicitly nullable: null clears the ceiling, which
    is a different intent from omitting the field and has to stay expressible.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    monthly_budget_usd: float | None = Field(default=None, ge=0)


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class TeamResponse(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class TeamDetailResponse(TeamResponse):
    """A team plus the caller's own standing in it.

    `your_role` saves the client a second request just to decide whether to
    render the admin controls.
    """

    member_count: int
    workspace_count: int
    your_role: Role


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    is_active: bool
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role = Role.MEMBER
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationResponse(ApiModel):
    id: uuid.UUID
    team_id: uuid.UUID
    email: str
    role: Role
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime


class InvitationCreatedResponse(BaseModel):
    """The one and only time the raw token is returned.

    It is not stored — only its hash is — so this response is the sole
    opportunity to deliver the link. Losing it means issuing a new invitation.
    """

    invitation: InvitationResponse
    accept_url: str
    token: str


class InvitationPreview(BaseModel):
    """What an invited person can see *before* authenticating.

    Deliberately thin: enough to decide whether to accept, and nothing that
    would leak the organization's shape to someone who merely guessed a token.
    """

    organization_name: str
    team_name: str
    email: str
    role: Role
    expires_at: datetime
    # True when this address already has an account, so the client can ask for
    # a password to sign in rather than one to create.
    requires_account: bool


class InvitationAccept(BaseModel):
    """Credentials for accepting as a new user.

    Omitted entirely when the caller is already authenticated.
    """

    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)


class UsageModelBreakdown(ApiModel):
    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: float


class UsageSummaryResponse(ApiModel):
    """Month-to-date spend against the ceiling, and what it went on."""

    period_start: datetime
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: float
    monthly_budget_usd: float | None
    budget_used_fraction: float | None
    budget_state: str
    by_model: list[UsageModelBreakdown]
