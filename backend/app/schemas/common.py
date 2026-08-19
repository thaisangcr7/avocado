"""Shapes shared across resources."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    """Base for every response model.

    `from_attributes` lets a DTO be built from an ORM instance explicitly —
    `DocumentResponse.model_validate(doc)` — which is how ORM objects are
    converted at the service boundary. Routers still never return an ORM model.
    """

    model_config = ConfigDict(from_attributes=True)


class ProblemDetail(BaseModel):
    """RFC 9457 error body. The only error shape this API emits."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: list[dict[str, Any]] | None = None
    request_id: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class MessageResponse(BaseModel):
    """A bare acknowledgement, for endpoints with nothing else to return."""

    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    checks: dict[str, str] = Field(default_factory=dict)
