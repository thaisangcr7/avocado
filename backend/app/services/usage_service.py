"""Records what each provider call cost.

Writing this on every call is what makes "which model is worth it" answerable
from data. A failure to log must never fail the request that produced it — the
user's answer matters more than the accounting row.
"""

from __future__ import annotations

import uuid

from app.clients.llm.router import ProviderRegistry
from app.core.logging import get_logger
from app.models.usage import ApiUsageLog
from app.repositories.usage import UsageRepository

log = get_logger(__name__)


class UsageService:
    def __init__(self, *, usage: UsageRepository, registry: ProviderRegistry) -> None:
        self._usage = usage
        self._registry = registry

    async def record(
        self,
        *,
        org_id: uuid.UUID | None,
        workspace_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        endpoint: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        operation: str = "generate",
        success: bool = True,
    ) -> None:
        if model is None:
            # No model was involved (an empty retrieval answered directly).
            # There is no cost to record.
            return

        try:
            provider_name = "unknown"
            cost = 0.0
            try:
                provider, spec = self._registry.find_model(model)
                provider_name = provider.name
                from app.clients.llm.base import Usage

                cost = spec.cost_usd(Usage(input_tokens=input_tokens, output_tokens=output_tokens))
            except Exception:
                # An unrecognised model id (a provider added one, or Auto
                # resolved to something new) should still be logged — with a
                # zero cost rather than not at all.
                log.debug("usage_model_unknown", model=model)

            await self._usage.record(
                ApiUsageLog(
                    org_id=org_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    endpoint=endpoint,
                    provider=provider_name,
                    model=model,
                    operation=operation,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    success=success,
                )
            )
            await self._usage.commit()
        except Exception:
            log.warning("usage_record_failed", model=model, exc_info=True)
