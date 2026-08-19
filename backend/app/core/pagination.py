"""Cursor pagination.

Opaque, stable cursors: an item's `created_at` plus its `id`, base64-encoded.
Offset pagination drifts when rows are inserted mid-scan; a keyset cursor does
not, which matters for feeds a user pages through while ingestion is running.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.errors import ValidationError

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True, slots=True)
class Cursor:
    created_at: datetime
    item_id: uuid.UUID

    def encode(self) -> str:
        raw = json.dumps(
            {"c": self.created_at.isoformat(), "i": str(self.item_id)},
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> Cursor:
        try:
            padded = value + "=" * (-len(value) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded))
            created = datetime.fromisoformat(data["c"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            return cls(created_at=created, item_id=uuid.UUID(data["i"]))
        except (
            binascii.Error,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValidationError("Malformed pagination cursor.") from exc


class PageParams(BaseModel):
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = None

    def decoded_cursor(self) -> Cursor | None:
        return Cursor.decode(self.cursor) if self.cursor else None


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
