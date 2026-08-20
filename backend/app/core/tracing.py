"""OpenTelemetry tracing.

Off unless `OTEL_ENABLED` is set, because a tracing stack that fails to reach
its collector must never be the reason the API does not start. When it is on,
FastAPI, SQLAlchemy and httpx are instrumented, which covers the three places
latency actually goes: request handling, queries, and outbound provider calls.

Traces and logs are joined by putting the active trace id on every log line, so
a slow request found in a dashboard can be read as the log narrative that
produced it, rather than guessed at from timestamps.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

_instrumented = False


def add_trace_context(_logger: Any, _name: str, event_dict: dict) -> dict:
    """structlog processor: stamp the active trace on each line.

    Tolerates OpenTelemetry not being installed at all, so the logging
    pipeline has no hard dependency on the tracing extra.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return event_dict

    span = trace.get_current_span()
    context = span.get_span_context() if span else None
    if context is not None and context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def setup_tracing(settings: Settings) -> bool:
    """Configure the global tracer provider. Returns whether tracing is on.

    Safe to call more than once; the second call is a no-op rather than a
    second exporter quietly double-reporting every span.
    """
    global _instrumented
    if not settings.otel_enabled:
        return False
    if _instrumented:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        log.warning("otel_not_installed")
        return False

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "deployment.environment": settings.app_env,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter: Any = OTLPSpanExporter(endpoint=settings.otel_endpoint)
    else:
        # Console keeps this verifiable with no collector to stand up, which is
        # the difference between "tracing is configured" and "tracing works".
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _instrumented = True
    log.info(
        "tracing_enabled",
        exporter=settings.otel_exporter,
        endpoint=settings.otel_endpoint if settings.otel_exporter == "otlp" else None,
    )
    return True


def instrument_app(app: Any, settings: Settings) -> None:
    """Attach instrumentation to the app and its outbound clients."""
    if not settings.otel_enabled or not _instrumented:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError:
        return

    # /live and /ready are polled constantly by the orchestrator and would
    # otherwise dominate every trace view with noise nobody reads.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="live,ready")
    HTTPXClientInstrumentor().instrument()


def instrument_engine(settings: Settings, engine: Any) -> None:
    """Add query spans. Separate because the engine outlives no lifespan."""
    if not settings.otel_enabled or not _instrumented:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError:
        return
    # The async engine wraps a sync one, and that inner engine is what emits
    # the DBAPI events instrumentation hooks onto.
    SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))
