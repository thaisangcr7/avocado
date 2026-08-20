"""Rate limiting.

Architecture 13 asks for a per-organization limit, and that is the one that
protects the backend: cost is incurred per tenant, so one organization opening
twenty tabs must not be able to exhaust capacity for everyone else.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.middleware import RateLimitMiddleware, _org_claim, _stable_hash
from app.core.security import create_token
from tests.conftest import register_account

pytestmark = pytest.mark.anyio


@pytest.fixture
async def limited_client(app, settings):  # type: ignore[no-untyped-def]
    """The app with a deliberately tiny limit, so the boundary is reachable."""
    app.add_middleware(RateLimitMiddleware, limit=3, org_limit=5, window_seconds=60)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1"
    ) as client:
        yield client


def test_the_org_claim_is_read_without_verification(settings):
    """Reading it must not require a signature check — this runs before auth,
    and a limiter that does crypto or database work per request is an
    amplifier, not a defence."""
    import uuid

    org_id = uuid.uuid4()
    token = create_token(
        settings=settings,
        subject=uuid.uuid4(),
        token_type="access",  # noqa: S106
        org_id=org_id,
    )
    assert _org_claim(token) == str(org_id)


def test_a_malformed_token_has_no_org_claim():
    assert _org_claim("not-a-token") is None
    assert _org_claim("") is None


def test_the_bucket_hash_is_stable_across_processes():
    """Python's hash() is salted per process, so with several API replicas the
    same token would land in different buckets and the limit would scale with
    replica count."""
    assert _stable_hash("abc") == _stable_hash("abc")
    assert len(_stable_hash("abc")) == 32
    assert _stable_hash("abc") != _stable_hash("abd")


async def test_anonymous_traffic_is_limited_per_client(limited_client):
    """Login and registration attempts land here."""
    statuses = [
        (
            await limited_client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
        ).status_code
        for _ in range(6)
    ]
    assert 429 in statuses
    assert statuses.index(429) >= 3


async def test_a_rate_limited_response_uses_the_problem_envelope(limited_client):
    last = None
    for _ in range(8):
        last = await limited_client.post("/auth/login", json={"email": "a@b.com", "password": "x"})
    assert last is not None
    assert last.status_code == 429
    assert last.headers["content-type"].startswith("application/problem+json")
    body = last.json()
    assert body["title"] == "Too Many Requests"
    assert "Rate limit exceeded" in body["detail"]


async def test_an_organization_gets_a_larger_allowance_than_an_anonymous_client(
    client, limited_client
):
    """An organization is many people; its ceiling is correspondingly higher.

    Counted comparatively rather than exactly: `register_account` itself makes
    an authenticated call, so the organization's bucket is not empty when the
    loop starts. What matters is that authenticated traffic clears the
    anonymous ceiling, not the precise number.
    """
    anonymous_limit = 3
    account = await register_account(client, email="rl@acme.com", org="RL Co")

    allowed = 0
    for _ in range(5):
        response = await limited_client.get("/workspaces", headers=account["headers"])
        if response.status_code == 200:
            allowed += 1

    assert allowed > anonymous_limit, (
        f"only {allowed} authenticated requests succeeded, which is no better "
        f"than the anonymous limit of {anonymous_limit}"
    )


async def test_health_checks_are_never_rate_limited(limited_client):
    """A limiter that can take an instance out of the load balancer is worse
    than the traffic it is throttling."""
    for _ in range(12):
        assert (await limited_client.get("/live")).status_code == 200
