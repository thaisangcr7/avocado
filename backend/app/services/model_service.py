"""The model catalogue behind `GET /models`."""

from __future__ import annotations

from app.clients.llm.router import ProviderRegistry
from app.schemas.model import ModelCatalogResponse, ModelInfo


class ModelService:
    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def catalog(self) -> ModelCatalogResponse:
        models = self._registry.all_models()
        return ModelCatalogResponse(
            models=[
                ModelInfo(
                    id=m.id,
                    provider=m.provider,
                    display_name=m.display_name,
                    context_window=m.context_window,
                    max_output_tokens=m.max_output_tokens,
                    input_cost_per_mtok=m.input_cost_per_mtok,
                    output_cost_per_mtok=m.output_cost_per_mtok,
                    supports_vision=m.supports_vision,
                    tier=m.tier,
                )
                for m in models
            ],
            default_provider=self._registry.default_provider_name,
            # Auto needs at least one configured model to route to.
            auto_available=bool(models),
        )
