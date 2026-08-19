"""Registration, login, refresh and the authentication boundary."""

from __future__ import annotations

import pytest

from tests.conftest import register_account

pytestmark = pytest.mark.anyio


async def test_registration_provisions_a_full_tenant(client):
    """One call must yield a usable account: org, team, workspace and tokens."""
    account = await register_account(client, email="founder@acme.com", org="Acme Inc")

    me = await client.get("/auth/me", headers=account["headers"])
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "founder@acme.com"
    assert body["organization_name"] == "Acme Inc"
    # A default workspace exists, so the user has somewhere to upload to.
    assert len(body["workspace_ids"]) == 1


async def test_duplicate_email_is_rejected(client):
    await register_account(client, email="taken@acme.com")
    response = await client.post(
        "/auth/register",
        json={
            "email": "taken@acme.com",
            "password": "correct-horse-battery-staple",
            "organization_name": "Other",
        },
    )
    assert response.status_code == 409


async def test_login_succeeds_and_wrong_password_does_not(client):
    await register_account(client, email="login@acme.com")

    ok = await client.post(
        "/auth/login",
        json={"email": "login@acme.com", "password": "correct-horse-battery-staple"},
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post(
        "/auth/login", json={"email": "login@acme.com", "password": "wrong-password-x"}
    )
    assert bad.status_code == 401


async def test_unknown_account_and_wrong_password_are_indistinguishable(client):
    await register_account(client, email="real@acme.com")

    wrong_password = await client.post(
        "/auth/login", json={"email": "real@acme.com", "password": "wrong-password-x"}
    )
    unknown_user = await client.post(
        "/auth/login", json={"email": "ghost@acme.com", "password": "wrong-password-x"}
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


async def test_email_comparison_is_case_insensitive(client):
    await register_account(client, email="Case@Acme.com")
    response = await client.post(
        "/auth/login",
        json={"email": "case@acme.com", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200


async def test_refresh_exchanges_a_refresh_token_for_a_new_pair(client):
    account = await register_account(client)
    response = await client.post(
        "/auth/refresh", json={"refresh_token": account["tokens"]["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_an_access_token_cannot_be_used_to_refresh(client):
    account = await register_account(client)
    response = await client.post(
        "/auth/refresh", json={"refresh_token": account["tokens"]["access_token"]}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ],
)
async def test_protected_routes_require_a_valid_bearer_token(client, headers):
    response = await client.get("/workspaces", headers=headers)
    assert response.status_code == 401


async def test_short_passwords_are_rejected(client):
    response = await client.post(
        "/auth/register",
        json={"email": "weak@acme.com", "password": "short", "organization_name": "X"},
    )
    assert response.status_code == 422


async def test_errors_use_the_problem_details_envelope(client):
    response = await client.get("/workspaces")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert {"type", "title", "status", "detail"} <= body.keys()
    # A request id is always present so a failure can be traced in the logs.
    assert body["request_id"]
