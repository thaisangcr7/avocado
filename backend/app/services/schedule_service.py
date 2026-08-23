"""Schedules: what runs on its own, and when it next comes due.

The next run time is computed and stored rather than derived on every sweep.
That keeps the executor's query an index scan on a timestamp instead of parsing
every cron expression in the table on every tick — and it makes "when does this
next run" a value the UI can show rather than a calculation it has to repeat.
"""

from __future__ import annotations

import datetime
import uuid

from croniter import croniter

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.schedules import Schedule
from app.repositories.presets import PresetRepository
from app.repositories.schedules import ScheduleRepository
from app.schemas.schedules import ScheduleCreate, ScheduleResponse, ScheduleUpdate

log = get_logger(__name__)


def next_run_after(cron: str, after: datetime.datetime) -> datetime.datetime:
    """The next firing of `cron` strictly after `after`, in UTC.

    Always timezone-aware. A naive datetime compared against a `timestamptz`
    column is the kind of thing that works locally and drifts by an hour in a
    deployment that is not on UTC.
    """
    if after.tzinfo is None:
        after = after.replace(tzinfo=datetime.UTC)
    return croniter(cron, after).get_next(datetime.datetime)


class ScheduleService:
    def __init__(
        self, *, schedules: ScheduleRepository, presets: PresetRepository | None = None
    ) -> None:
        self._schedules = schedules
        self._presets = presets

    async def _require(self, schedule_id: uuid.UUID, workspace_id: uuid.UUID) -> Schedule:
        schedule = await self._schedules.get_scoped(schedule_id, workspace_id)
        if schedule is None:
            raise NotFoundError("Schedule not found.")
        return schedule

    async def list(self, workspace_id: uuid.UUID) -> list[ScheduleResponse]:
        rows = await self._schedules.list_for_workspace(workspace_id)
        return [ScheduleResponse.model_validate(row) for row in rows]

    async def create(
        self,
        payload: ScheduleCreate,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> ScheduleResponse:
        await self._check_preset(payload.preset_id, user_id=user_id, org_id=org_id)

        now = datetime.datetime.now(datetime.UTC)
        schedule = await self._schedules.add(
            Schedule(
                workspace_id=workspace_id,
                created_by_user_id=user_id,
                name=payload.name,
                prompt=payload.prompt,
                cron=payload.cron,
                preset_id=payload.preset_id,
                enabled=payload.enabled,
                next_run_at=next_run_after(payload.cron, now),
            )
        )
        await self._schedules.commit()
        await self._schedules.refresh(schedule)
        log.info("schedule_created", schedule=str(schedule.id), cron=payload.cron)
        return ScheduleResponse.model_validate(schedule)

    async def update(
        self,
        schedule_id: uuid.UUID,
        payload: ScheduleUpdate,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> ScheduleResponse:
        schedule = await self._require(schedule_id, workspace_id)

        if payload.preset_id is not None:
            await self._check_preset(payload.preset_id, user_id=user_id, org_id=org_id)
            schedule.preset_id = payload.preset_id

        for field in ("name", "prompt", "enabled"):
            value = getattr(payload, field)
            if value is not None:
                setattr(schedule, field, value)

        # A changed recurrence has to move the next run, or the old time stands
        # and the edit appears to have done nothing until it fires wrongly.
        if payload.cron is not None and payload.cron != schedule.cron:
            schedule.cron = payload.cron
            schedule.next_run_at = next_run_after(payload.cron, datetime.datetime.now(datetime.UTC))

        await self._schedules.commit()
        await self._schedules.refresh(schedule)
        return ScheduleResponse.model_validate(schedule)

    async def delete(self, schedule_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        schedule = await self._require(schedule_id, workspace_id)
        await self._schedules.delete(schedule)
        await self._schedules.commit()

    async def _check_preset(
        self, preset_id: uuid.UUID | None, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        """A schedule may only name a preset its author can actually see.

        Without this, a preset id pasted from anywhere would run somebody
        else's private instruction on a timer.
        """
        if preset_id is None or self._presets is None:
            return
        if await self._presets.get_visible(preset_id, user_id, org_id) is None:
            raise NotFoundError("Preset not found.")
