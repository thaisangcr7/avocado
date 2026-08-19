"""Cross-cutting request concerns.

The exception handlers here are the *only* place an error response body is
constructed. That is what makes the envelope identical on every route and
guarantees no handler can leak an internal message while another does not.
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import AvocadoError, RateLimitedError
from app.core.logging import get_logger, request_id_var, user_id_var, workspace_id_var
from app.schemas.common import ProblemDetail

log = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


def _problem(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
    error_type: str = "about:blank",
    errors: list[dict] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        type=error_type,
        title=title,
        status=status_code,
        detail=detail,
        instance=str(request.url.path),
        errors=errors,
        request_id=request_id_var.get(),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_JSON,
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, binds log context, and times the request."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        # Honour an upstream id so a trace survives a proxy hop.
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        user_token = user_id_var.set(None)
        workspace_token = workspace_id_var.set(None)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Logged here with full context; the handler below turns it into a
            # response body.
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            raise
        finally:
            request_id_var.reset(token)
            user_id_var.reset(user_token)
            workspace_id_var.reset(workspace_token)

        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["x-request-id"] = request_id
        # Health checks would otherwise dominate the log at no information gain.
        if not request.url.path.endswith(("/health", "/live", "/ready")):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limit, keyed by client.

    Backed by Redis when available so the limit holds across API replicas; an
    in-process fallback keeps local development working without Redis. The
    fallback is per-process and therefore weaker — which is fine for one
    machine and explicitly not the production path.
    """

    def __init__(self, app, *, limit: int, window_seconds: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._limit = limit
        self._window = window_seconds
        self._local: dict[str, tuple[int, float]] = {}

    def _client_key(self, request: Request) -> str:
        # Authenticated callers are limited per token, anonymous ones per IP.
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return f"rl:token:{hash(auth[7:]) & 0xFFFFFFFF}"
        client = request.client.host if request.client else "unknown"
        return f"rl:ip:{client}"

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path.endswith(("/health", "/live", "/ready")):
            return await call_next(request)

        key = self._client_key(request)
        # Read the client off app state per request: middleware is constructed
        # before the lifespan runs, so there is no Redis connection to capture
        # at __init__ time.
        redis = getattr(request.app.state, "redis", None)
        try:
            allowed = await self._check(key, redis)
        except Exception:
            # A rate limiter that is down must not take the API down with it.
            log.warning("rate_limit_check_failed", exc_info=True)
            allowed = True

        if not allowed:
            return _problem(
                request,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                title=RateLimitedError.title,
                detail=f"Rate limit exceeded: {self._limit} requests per "
                f"{self._window} seconds.",
                error_type=RateLimitedError.error_type,
            )
        return await call_next(request)

    async def _check(self, key: str, redis) -> bool:  # type: ignore[no-untyped-def]
        if redis is not None:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self._window)
            return count <= self._limit

        now = time.monotonic()
        count, expires = self._local.get(key, (0, now + self._window))
        if now > expires:
            count, expires = 0, now + self._window
        count += 1
        self._local[key] = (count, expires)
        return count <= self._limit


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AvocadoError)
    async def handle_avocado_error(request: Request, exc: AvocadoError) -> JSONResponse:
        return _problem(
            request,
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            error_type=exc.error_type,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _problem(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation Failed",
            detail="The request body or parameters are invalid.",
            error_type="https://avocado.dev/errors/validation",
            errors=[
                {
                    "field": ".".join(str(p) for p in error["loc"][1:]),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ],
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(
            request,
            status_code=exc.status_code,
            title=str(exc.detail) if exc.status_code < 500 else "Internal Server Error",
            detail=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The detail is deliberately generic: an unhandled exception's message
        # can contain anything, including connection strings.
        log.exception("unhandled_exception", path=request.url.path)
        return _problem(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal Server Error",
            detail="An unexpected error occurred. The request id can be used to "
            "trace it in the logs.",
        )
