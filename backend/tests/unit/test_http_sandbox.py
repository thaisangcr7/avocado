"""The sandbox client that delegates to the runner service.

The property that matters is what it does *not* send: limits. A client able to
name its own timeout and memory ceiling could name unlimited ones, and putting
the sandbox behind an API would have weakened it rather than contained it.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.clients.sandbox.base import SandboxDataset, SandboxLimits
from app.clients.sandbox.http_sandbox import HttpSandbox

pytestmark = pytest.mark.anyio

LIMITS = SandboxLimits(timeout_seconds=30, memory_mb=512, cpus=1.0, max_output_bytes=1_048_576)


def stub_transport(handler):
    """Intercept requests without a network or a running service."""
    return httpx.MockTransport(handler)


@pytest.fixture
def captured():
    return {}


# Captured once, at import. Re-reading httpx.AsyncClient inside the helper
# would wrap an already-patched client on a second call, and the first
# handler's transport would win.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def make_sandbox(monkeypatch, handler) -> HttpSandbox:
    def patched(*args, **kwargs):
        kwargs["transport"] = stub_transport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    return HttpSandbox("http://sandbox:8080", "shared-secret")


async def test_the_request_carries_no_limits(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        captured["token"] = request.headers.get("X-Sandbox-Token")
        return httpx.Response(200, json={"success": True, "stdout": "ok"})

    sandbox = make_sandbox(monkeypatch, handler)
    await sandbox.run(
        code="result = 1",
        datasets=[SandboxDataset(variable="df", filename="d.csv", content=b"a,b\n1,2\n")],
        limits=LIMITS,
    )

    body = captured["body"]
    assert set(body) == {"code", "datasets"}
    for forbidden in ("timeout_seconds", "memory_mb", "cpus", "limits"):
        assert forbidden not in body, f"{forbidden} must be the runner's decision"


async def test_it_authenticates(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["token"] = request.headers.get("X-Sandbox-Token")
        return httpx.Response(200, json={"success": True})

    sandbox = make_sandbox(monkeypatch, handler)
    await sandbox.run(code="result = 1", datasets=[], limits=LIMITS)
    assert captured["token"] == "shared-secret"


async def test_datasets_are_base64_encoded(monkeypatch, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    sandbox = make_sandbox(monkeypatch, handler)
    await sandbox.run(
        code="result = 1",
        datasets=[SandboxDataset(variable="df", filename="d.csv", content=b"raw,bytes\n")],
        limits=LIMITS,
    )

    dataset = captured["body"]["datasets"][0]
    assert base64.b64decode(dataset["content_b64"]) == b"raw,bytes\n"


async def test_a_result_is_carried_back_faithfully(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "stdout": "total: 350",
                "tables": [{"name": "result", "columns": ["a"], "rows": [[1]]}],
                "scalars": {"result": 350},
                "chart_png_b64": "abc",
                "execution_ms": 1234,
            },
        )

    sandbox = make_sandbox(monkeypatch, handler)
    result = await sandbox.run(code="result = 1", datasets=[], limits=LIMITS)

    assert result.success is True
    assert result.stdout == "total: 350"
    assert result.tables[0]["columns"] == ["a"]
    assert result.scalars["result"] == 350
    assert result.chart_png_b64 == "abc"
    assert result.execution_ms == 1234


async def test_a_timeout_is_reported_as_one(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": False,
                "timed_out": True,
                "error": "Analysis exceeded the 30s time limit.",
            },
        )

    sandbox = make_sandbox(monkeypatch, handler)
    result = await sandbox.run(code="while True: pass", datasets=[], limits=LIMITS)

    assert result.success is False
    assert result.timed_out is True


async def test_an_unreachable_runner_fails_closed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    sandbox = make_sandbox(monkeypatch, handler)
    result = await sandbox.run(code="result = 1", datasets=[], limits=LIMITS)

    # Never a silent success: analysis that could not run must say so.
    assert result.success is False
    assert "unreachable" in result.error


async def test_a_refused_request_fails_closed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorised."})

    sandbox = make_sandbox(monkeypatch, handler)
    result = await sandbox.run(code="result = 1", datasets=[], limits=LIMITS)

    assert result.success is False
    assert "401" in result.error


async def test_availability_follows_the_runners_own_report(monkeypatch):
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "docker_available": False})

    sandbox = make_sandbox(monkeypatch, unavailable)
    assert await sandbox.available() is False

    def available(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "docker_available": True})

    sandbox = make_sandbox(monkeypatch, available)
    assert await sandbox.available() is True
