"""Auth routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUserDep, get_auth_service
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: AuthServiceDep) -> TokenResponse:
    """Create an organization, its first user, a default team and workspace."""
    return await service.register(payload)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, service: AuthServiceDep) -> TokenResponse:
    return await service.login(payload)


@router.post("/demo-session", response_model=TokenResponse)
async def demo_session(service: AuthServiceDep) -> TokenResponse:
    return await service.demo_session()


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, service: AuthServiceDep) -> TokenResponse:
    return await service.refresh(payload.refresh_token)


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: CurrentUserDep, service: AuthServiceDep) -> CurrentUserResponse:
    return await service.current_user(user.id)
