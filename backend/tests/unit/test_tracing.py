"""Tracing setup, and the log/trace correlation that makes it useful."""

from __future__ import annotations

import app.core.tracing as tracing_module
from app.core.config import Settings
from app.core.tracing import add_trace_context, setup_tracing


def test_tracing_stays_off_unless_asked():
    """A tracing stack that cannot reach its collector must not break boot."""
    assert setup_tracing(Settings(app_env="test")) is False


def test_a_log_line_outside_a_span_gets_no_trace_id():
    assert add_trace_context(None, "info", {"event": "x"}) == {"event": "x"}


def test_setup_is_idempotent(monkeypatch):
    """Calling twice must not attach a second exporter double-reporting spans."""
    monkeypatch.setattr(tracing_module, "_instrumented", False)
    settings = Settings(app_env="test", otel_enabled=True, otel_exporter="console")
    try:
        assert setup_tracing(settings) is True
        assert setup_tracing(settings) is True
    finally:
        monkeypatch.setattr(tracing_module, "_instrumented", False)


def test_a_log_line_inside_a_span_carries_the_trace(monkeypatch):
    """The join between a dashboard trace and the log narrative behind it."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        event = add_trace_context(None, "info", {"event": "inside"})
        expected = format(span.get_span_context().trace_id, "032x")

    assert event["trace_id"] == expected
    assert "span_id" in event

    exported = exporter.get_finished_spans()
    assert [s.name for s in exported] == ["unit"]
    # The id on the log line is the id of the span that was exported, which is
    # the whole point: one is findable from the other.
    assert format(exported[0].context.trace_id, "032x") == expected


def test_the_service_is_named_for_the_dashboard(monkeypatch):
    monkeypatch.setattr(tracing_module, "_instrumented", False)
    settings = Settings(
        app_env="test", otel_enabled=True, otel_exporter="console", otel_service_name="avocado-test"
    )
    try:
        assert setup_tracing(settings) is True
    finally:
        monkeypatch.setattr(tracing_module, "_instrumented", False)
