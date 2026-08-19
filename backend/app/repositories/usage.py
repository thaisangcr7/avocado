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
