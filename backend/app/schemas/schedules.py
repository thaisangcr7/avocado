"""Schedule resources."""

from __future__ import annotations

import datetime
import uuid

from croniter import croniter
from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ApiModel


def validate_cron(value: str) -> str:
    """Reject an expression that would never fire, at the boundary.

    A schedule whose cron is wrong does not fail loudly — it simply never runs,
    and nobody notices for a week. Checking it here makes that a 422 at the
    moment someone types it.
    """
    value = value.strip()
    if not croniter.is_valid(value):
        raise ValueError(
            "That is not a valid cron expression. Five fields: minute, hour, "
            "day of month, month, day of week — for example '0 9 * * 1-5'."
        )
    return value


class ScheduleBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=8000)
    cron: str = Field(min_length=1, max_length=120)
    preset_id: uuid.UUID | None = None
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, value: str) -> str:
        return validate_cron(value)


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    cron: str | None = Field(default=None, min_length=1, max_length=120)
    preset_id: uuid.UUID | None = None
    enabled: bool | None = None

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        return validate_cron(value) if value is not None else None


class ScheduleResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    prompt: str
    cron: str
    preset_id: uuid.UUID | None
    enabled: bool
    next_run_at: datetime.datetime
    last_run_at: datetime.datetime | None
    # What happened last time, when it went wrong. A schedule failing quietly
    # for a week is the failure this is here to prevent.
    last_error: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
