"""Auth request/response models."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ApiModel

MIN_PASSWORD_LENGTH = 12


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        # Length does most of the work; this rejects the degenerate cases a
        # length check alone lets through ("aaaaaaaaaaaa").
        if len(set(v)) < 5:
            raise ValueError("Password is too repetitive.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the scheme name, not a credential
    expires_in: int


class UserResponse(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    org_id: uuid.UUID
    is_active: bool


class CurrentUserResponse(UserResponse):
    """`GET /auth/me` — the user plus what they can reach."""

    organization_name: str
    workspace_ids: list[uuid.UUID] = []
