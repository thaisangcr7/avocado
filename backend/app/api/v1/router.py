"""Aggregates every v1 route under one router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analysis,
    auth,
    conversations,
    documents,
    health,
    models,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(documents.router)
api_router.include_router(conversations.router)
api_router.include_router(analysis.router)
api_router.include_router(models.router)
