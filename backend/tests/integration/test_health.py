"""Liveness and readiness."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_liveness_never_depends_on_a_downstream(client):
    """A database blip must not restart otherwise-healthy containers."""
    response = await client.get("/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_reports_each_dependency(client):
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    # Every dependency is named, whether configured or not.
    assert {
        "database",
        "redis",
        "sandbox",
        "voice",
        "llm",
        "embeddings",
    } <= body["checks"].keys()


async def test_readiness_stays_ok_when_optional_dependencies_are_absent(client, app):
    """A missing sandbox or transcriber degrades a feature; it must not pull
    the instance out of the load balancer."""
    app.state.sandbox = None
    app.state.transcriber = None

    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["voice"] == "disabled"


async def test_health_endpoints_are_public(client):
    assert (await client.get("/live")).status_code == 200
    assert (await client.get("/ready")).status_code == 200


async def test_every_response_carries_a_request_id(client):
    response = await client.get("/live")
    assert response.headers["x-request-id"]


async def test_an_upstream_request_id_is_preserved(client):
    """A trace has to survive a proxy hop."""
    response = await client.get("/live", headers={"x-request-id": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"
