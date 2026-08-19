"""Cursor encoding."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.core.pagination import Cursor, PageParams


def test_cursor_round_trips():
    original = Cursor(created_at=datetime.now(UTC), item_id=uuid.uuid4())
    decoded = Cursor.decode(original.encode())
    assert decoded.item_id == original.item_id
    assert decoded.created_at == original.created_at


def test_cursor_is_opaque_and_url_safe():
    encoded = Cursor(created_at=datetime.now(UTC), item_id=uuid.uuid4()).encode()
    assert "=" not in encoded
    assert "/" not in encoded and "+" not in encoded


@pytest.mark.parametrize("bad", ["not-a-cursor", "!!!!", "", "eyJ4Ijog"])
def test_malformed_cursor_is_rejected(bad):
    with pytest.raises(ValidationError):
        Cursor.decode(bad)


def test_naive_timestamps_are_treated_as_utc():
    encoded = Cursor(created_at=datetime(2026, 1, 1, 12, 0, 0), item_id=uuid.uuid4()).encode()
    assert Cursor.decode(encoded).created_at.tzinfo is not None


def test_page_params_reject_oversized_limits():
    with pytest.raises(PydanticValidationError):
        PageParams(limit=10_000)
