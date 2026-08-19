"""Password hashing and token handling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", secret_key="a" * 48)


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")
    assert first != second  # distinct salts
    assert verify_password("correct-horse-battery", first)
    assert verify_password("correct-horse-battery", second)


def test_wrong_password_is_rejected():
    assert not verify_password("wrong", hash_password("right-password-here"))


def test_malformed_hash_does_not_raise():
    assert not verify_password("anything", "not-a-hash")


def test_access_and_refresh_tokens_are_not_interchangeable(settings):
    user_id = uuid.uuid4()
    access = create_token(settings=settings, subject=user_id, token_type="access")
    refresh = create_token(settings=settings, subject=user_id, token_type="refresh")

    decoded = decode_token(settings=settings, token=access, expected_type="access")
    assert decoded["sub"] == str(user_id)

    # A refresh token must not be usable where an access token is required.
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=refresh, expected_type="access")
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=access, expected_type="refresh")


def test_expired_token_is_rejected(settings):
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "access",
            "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=expired, expected_type="access")


def test_token_signed_with_another_key_is_rejected(settings):
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "access",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        "a-different-secret-entirely",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=forged, expected_type="access")


def test_unsigned_token_is_rejected(settings):
    """`alg: none` is the classic JWT bypass; the decoder must refuse it."""
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "access",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=unsigned, expected_type="access")


def test_token_without_required_claims_is_rejected(settings):
    incomplete = jwt.encode({"sub": "x"}, settings.secret_key, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=incomplete, expected_type="access")
