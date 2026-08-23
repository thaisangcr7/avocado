"""Preset resources.

Shape rules live here, on the models, so they are part of the published API
schema. Anything needing a database lookup — is this slug taken, may this
person publish — is a state rule and belongs in the service.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import PresetScope
from app.schemas.common import ApiModel

# What a user types after the slash. Constrained to what reads unambiguously in
# a composer: no spaces to end the token early, no uppercase to make `/Sage`
# and `/sage` different commands.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}[a-z0-9]$|^[a-z0-9]$")

# Long enough for a genuine house style, short enough that it cannot crowd out
# the conversation it is meant to steer.
MAX_SYSTEM_PROMPT_CHARS = 20_000


def slugify(name: str) -> str:
    """A usable slash command from a display name.

    Only a starting point — the service still has to resolve a collision,
    because two people naming a preset "Sage" is not a validation error.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80].rstrip("-") or "preset"


class PresetBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(min_length=1, max_length=MAX_SYSTEM_PROMPT_CHARS)
    model_hint: str | None = Field(default=None, max_length=120)

    @field_validator("name", "description")
    @classmethod
    def _no_surrounding_space(cls, value: str) -> str:
        return value.strip()

    @field_validator("system_prompt")
    @classmethod
    def _prompt_is_not_only_space(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A preset needs an instruction, not an empty one.")
        return value.strip()


class PresetCreate(PresetBase):
    # Optional: derived from the name when absent, which is what the UI does.
    slug: str | None = Field(default=None, max_length=80)
    scope: PresetScope = PresetScope.PRIVATE

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower().lstrip("/")
        if not SLUG_PATTERN.match(value):
            raise ValueError(
                "A slash command must be lowercase letters, digits and dashes — "
                "it is what someone types after '/'."
            )
        return value


class PresetUpdate(BaseModel):
    """Every field optional: a rename should not require resending the prompt."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    system_prompt: str | None = Field(
        default=None, min_length=1, max_length=MAX_SYSTEM_PROMPT_CHARS
    )
    model_hint: str | None = Field(default=None, max_length=120)
    scope: PresetScope | None = None


class PresetResponse(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    system_prompt: str
    model_hint: str | None
    scope: PresetScope
    is_native: bool
    version: int
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    # Reader-relative, so the same preset renders differently for two people.
    # Computed by the service; not columns on the row.
    pinned: bool = False
    is_mine: bool = False
    can_edit: bool = False


class PresetListResponse(ApiModel):
    presets: list[PresetResponse]
    total: int


class PresetShareRequest(BaseModel):
    user_id: uuid.UUID
