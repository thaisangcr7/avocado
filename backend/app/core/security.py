"""Password hashing and JWT issue/verify.

Auth is local (email + password -> JWT) rather than Clerk/Auth0. That keeps
local development and CI free of an external dependency and makes the whole
auth path testable; the token-issuing surface is small enough that swapping in
a hosted IdP later means replacing `AuthService`, not the routers.

Access tokens are short-lived; refresh tokens are separate, longer-lived, and
carry a distinct `typ` claim so one can never be replayed as the other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    return True


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash predates the current argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return True


def create_token(
    *,
    settings: Settings,
    subject: uuid.UUID | str,
    token_type: TokenType,
    org_id: uuid.UUID | str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    ttl = (
        timedelta(minutes=settings.access_token_ttl_minutes)
        if token_type == "access"  # noqa: S105 - a token kind, not a secret
        else timedelta(days=settings.refresh_token_ttl_days)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if org_id is not None:
        payload["org"] = str(org_id)
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(*, settings: Settings, token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token, or raise `AuthenticationError`.

    The error message is deliberately uniform: a caller learns that the token
    was unusable, not *why*, which keeps token-probing uninformative.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token.") from exc

    if payload.get("typ") != expected_type:
        raise AuthenticationError("Invalid token.")
    return payload
