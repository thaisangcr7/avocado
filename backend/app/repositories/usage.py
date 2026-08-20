"""API usage log writes and aggregation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.models.usage import ApiUsageLog
from app.repositories.base import BaseRepository


class UsageRepository(BaseRepository[ApiUsageLog]):
    model = ApiUsageLog

    async def record(self, entry: ApiUsageLog) -> ApiUsageLog:
        return await self.add(entry)

    async def summarise_for_org(
        self, org_id: uuid.UUID, *, since: datetime | None = None
    ) -> dict[str, float | int]:
        stmt = select(
            func.count(ApiUsageLog.id),
            func.coalesce(func.sum(ApiUsageLog.input_tokens), 0),
            func.coalesce(func.sum(ApiUsageLog.output_tokens), 0),
            func.coalesce(func.sum(ApiUsageLog.cost_usd), 0.0),
            func.coalesce(func.avg(ApiUsageLog.latency_ms), 0.0),
        ).where(ApiUsageLog.org_id == org_id)
        if since is not None:
            stmt = stmt.where(ApiUsageLog.created_at >= since)

        calls, input_tokens, output_tokens, cost, latency = (
            await self._session.execute(stmt)
        ).one()
        return {
            "calls": int(calls),
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cost_usd": round(float(cost), 6),
            "avg_latency_ms": round(float(latency), 1),
        }

    async def breakdown_by_model(
        self, org_id: uuid.UUID, *, since: datetime | None = None
    ) -> list[dict[str, float | int | str]]:
        """Per-model cost and latency, most expensive first.

        The summary says what was spent; this says what it was spent on, which
        is the number that makes "is the frontier model worth it here" a
        decision rather than a guess.
        """
        stmt = (
            select(
                ApiUsageLog.provider,
                ApiUsageLog.model,
                func.count(ApiUsageLog.id),
                func.coalesce(func.sum(ApiUsageLog.input_tokens), 0),
                func.coalesce(func.sum(ApiUsageLog.output_tokens), 0),
                func.coalesce(func.sum(ApiUsageLog.cost_usd), 0.0),
                func.coalesce(func.avg(ApiUsageLog.latency_ms), 0.0),
            )
            .where(ApiUsageLog.org_id == org_id)
            .group_by(ApiUsageLog.provider, ApiUsageLog.model)
            .order_by(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0.0).desc())
        )
        if since is not None:
            stmt = stmt.where(ApiUsageLog.created_at >= since)

        return [
            {
                "provider": provider,
                "model": model,
                "calls": int(calls),
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "cost_usd": round(float(cost), 6),
                "avg_latency_ms": round(float(latency), 1),
            }
            for provider, model, calls, input_tokens, output_tokens, cost, latency in (
                await self._session.execute(stmt)
            ).all()
        ]

    async def month_to_date_cost(self, org_id: uuid.UUID, *, now: datetime) -> float:
        """Spend since the start of the current UTC month.

        Budgets reset on a calendar boundary rather than a rolling window so the
        number a user sees matches the one they would compute themselves.
        """
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cost = await self._session.scalar(
            select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0.0)).where(
                ApiUsageLog.org_id == org_id, ApiUsageLog.created_at >= start
            )
        )
        return float(cost or 0.0)
