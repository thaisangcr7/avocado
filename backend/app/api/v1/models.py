"""Model catalogue route."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, get_model_service
from app.schemas.model import ModelCatalogResponse
from app.services.model_service import ModelService

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelCatalogResponse)
async def list_models(
    _user: CurrentUserDep,
    service: Annotated[ModelService, Depends(get_model_service)],
) -> ModelCatalogResponse:
    """Every configured model, for the picker. Auto is the default."""
    return service.catalog()
