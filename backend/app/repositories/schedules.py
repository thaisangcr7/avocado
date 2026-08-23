"""Data access for schedules."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select

from app.models.schedules import Schedule
from app.repositories.base import WorkspaceScopedRepository


class ScheduleRepository(WorkspaceScopedRepository[Schedule]):
    model = Schedule

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[Schedule]:
        stmt = self._scoped_select(workspace_id).order_by(
            Schedule.enabled.desc(), Schedule.next_run_at.asc()
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def due(self, now: datetime.datetime, *, limit: int = 50) -> list[Schedule]:
        """Everything enabled whose time has come.

        Deliberately not workspace-scoped: this is the executor's query and it
        runs for every tenant at once. It is the one read in this codebase that
        crosses workspaces on purpose, which is why it lives in its own method
        with this comment rather than as an argument to a general one.
        """
        stmt = (
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
