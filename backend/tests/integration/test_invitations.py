"""The invite flow.

An invitation token is a capability: holding it is what grants the join. So
these tests treat it as a credential — checking that it is never recoverable
from storage, that every failure mode is indistinguishable, and that it cannot
be redirected to a different account or organization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.invitations import Invitation, InvitationStatus
from app.services.invitation_service import hash_token
from tests.conftest import register_account

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
async def org(client):
    founder = await register_account(client, email="founder@acme.com", org="Acme")
    teams = await client.get("/teams", headers=founder["headers"])
    return {"founder": founder, "team_id": teams.json()[0]["id"]}


async def team_without_founder(client, org, name: str) -> str:
    """A team the founder can administer but is not a member of.

    `create_team` joins the creator, so inviting them straight back would hit
    the already-a-member check rather than exercising the path under test.
    """
    created = await client.post("/teams", json={"name": name}, headers=org["founder"]["headers"])
    team_id = created.json()["id"]
    founder_id = (await client.get("/auth/me", headers=org["founder"]["headers"])).json()["id"]
    left = await client.delete(
        f"/teams/{team_id}/members/{founder_id}", headers=org["founder"]["headers"]
    )
    assert left.status_code == 200, left.text
    return team_id


async def invite(client, org, email="new@acme.com", role="member", **kwargs):
    return await client.post(
        f"/teams/{org['team_id']}/invitations",
        json={"email": email, "role": role, **kwargs},
        headers=org["founder"]["headers"],
    )


# --- issuing ---------------------------------------------------------------


async def test_an_invitation_returns_a_link_exactly_once(client, org):
    response = await invite(client, org)
    assert response.status_code == 201
    body = response.json()

    assert body["token"]
    assert body["token"] in body["accept_url"]
    assert body["invitation"]["status"] == "pending"
    assert body["invitation"]["email"] == "new@acme.com"

    # Listing an invitation must never hand the token back — the response above
    # is the only place it exists.
    listed = await client.get(
        f"/teams/{org['team_id']}/invitations", headers=org["founder"]["headers"]
    )
    assert listed.status_code == 200
    assert "token" not in listed.json()[0]


async def test_only_the_hash_of_the_token_is_stored(client, org, session):
    """A database read must not be able to reconstruct a working invite link."""
    token = (await invite(client, org)).json()["token"]

    stored = (await session.execute(select(Invitation))).scalars().first()
    assert stored is not None
    assert stored.token_hash != token
    assert stored.token_hash == hash_token(token)
    assert token not in stored.token_hash


async def test_a_member_cannot_invite(client, org):
    token = (await invite(client, org, email="plain@acme.com")).json()["token"]
    await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})

    signed_in = await client.post(
        "/auth/login", json={"email": "plain@acme.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    response = await client.post(
        f"/teams/{org['team_id']}/invitations",
        json={"email": "someone@acme.com", "role": "member"},
        headers=headers,
    )
    assert response.status_code == 403


async def test_nobody_can_invite_above_their_own_role(client, org):
    """Otherwise privilege escalation just goes through a second account."""
    token = (await invite(client, org, email="ta@acme.com", role="team_admin")).json()["token"]
    await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})
    signed_in = await client.post(
        "/auth/login", json={"email": "ta@acme.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    response = await client.post(
        f"/teams/{org['team_id']}/invitations",
        json={"email": "escalate@acme.com", "role": "org_admin"},
        headers=headers,
    )
    assert response.status_code == 422
    assert "above your own" in response.json()["detail"]


async def test_a_duplicate_pending_invitation_is_refused(client, org):
    await invite(client, org)
    again = await invite(client, org)
    assert again.status_code == 409


async def test_inviting_an_existing_member_is_refused(client, org):
    token = (await invite(client, org, email="already@acme.com")).json()["token"]
    await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})

    response = await invite(client, org, email="already@acme.com")
    assert response.status_code == 409
    assert "already a member" in response.json()["detail"]


async def test_inviting_someone_from_another_organization_is_refused(client, org):
    """An address identifies exactly one account across the system."""
    await register_account(client, email="elsewhere@other.com", org="Other Co")

    response = await invite(client, org, email="elsewhere@other.com")
    assert response.status_code == 409
    assert "another" in response.json()["detail"]


async def test_an_outsider_cannot_invite_into_a_team(client, org):
    outsider = await register_account(client, email="outsider@x.com", org="X")
    response = await client.post(
        f"/teams/{org['team_id']}/invitations",
        json={"email": "victim@acme.com", "role": "org_admin"},
        headers=outsider["headers"],
    )
    assert response.status_code == 404


# --- previewing ------------------------------------------------------------


async def test_preview_needs_no_account(client, org):
    """The recipient may not have one yet, so this is deliberately anonymous."""
    token = (await invite(client, org)).json()["token"]

    response = await client.get(f"/invitations/{token}")
    assert response.status_code == 200
    body = response.json()
    assert body["organization_name"] == "Acme"
    assert body["email"] == "new@acme.com"
    assert body["role"] == "member"
    assert body["requires_account"] is True


async def test_preview_says_when_an_account_already_exists(client, org):
    team_id = await team_without_founder(client, org, "Second")
    response = await client.post(
        f"/teams/{team_id}/invitations",
        json={"email": "founder@acme.com", "role": "member"},
        headers=org["founder"]["headers"],
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]

    preview = await client.get(f"/invitations/{token}")
    assert preview.json()["requires_account"] is False


async def test_preview_reveals_nothing_for_an_unknown_token(client):
    response = await client.get(f"/invitations/{'x' * 43}")
    assert response.status_code == 404
    assert response.json()["detail"] == "This invitation is not valid."


# --- accepting -------------------------------------------------------------


async def test_accepting_creates_an_account_and_signs_it_in(client, org):
    token = (await invite(client, org)).json()["token"]

    response = await client.post(
        f"/invitations/{token}/accept",
        json={"password": PASSWORD, "full_name": "New Person"},
    )
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["access_token"]

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = await client.get("/auth/me", headers=headers)
    assert me.json()["email"] == "new@acme.com"
    # Joined the inviting organization — not one of their choosing.
    assert me.json()["organization_name"] == "Acme"

    members = await client.get(
        f"/teams/{org['team_id']}/members", headers=org["founder"]["headers"]
    )
    assert "new@acme.com" in [m["email"] for m in members.json()]


async def test_the_new_account_can_reach_the_teams_workspaces(client, org):
    """Joining has to actually grant access, or the invitation did nothing."""
    token = (await invite(client, org)).json()["token"]
    accepted = await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})
    headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}

    workspaces = await client.get("/workspaces", headers=headers)
    assert workspaces.status_code == 200
    assert workspaces.json(), "an invited member should see the team's workspaces"
    assert workspaces.json()[0]["id"] == org["founder"]["workspace_id"]


async def test_accepting_without_a_password_is_refused(client, org):
    token = (await invite(client, org)).json()["token"]
    response = await client.post(f"/invitations/{token}/accept", json={})
    assert response.status_code == 422


async def test_a_weak_password_is_refused(client, org):
    token = (await invite(client, org)).json()["token"]
    response = await client.post(f"/invitations/{token}/accept", json={"password": "short"})
    assert response.status_code == 422


async def test_an_invitation_cannot_be_used_twice(client, org):
    token = (await invite(client, org)).json()["token"]
    assert (
        await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})
    ).status_code == 200

    again = await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})
    assert again.status_code == 404


async def test_a_signed_in_user_cannot_accept_someone_elses_invitation(client, org):
    """A leaked link must not let a different account join."""
    other = await register_account(client, email="bystander@acme.com", org="Bystander Co")
    token = (await invite(client, org)).json()["token"]

    response = await client.post(f"/invitations/{token}/accept", json={}, headers=other["headers"])
    assert response.status_code == 422
    assert "different address" in response.json()["detail"]


async def test_an_existing_account_must_sign_in_before_accepting(client, org):
    """Otherwise the invitation link would work as a password."""
    team_id = await team_without_founder(client, org, "Second")
    created = await client.post(
        f"/teams/{team_id}/invitations",
        json={"email": "founder@acme.com", "role": "member"},
        headers=org["founder"]["headers"],
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]

    anonymous = await client.post(f"/invitations/{token}/accept", json={})
    assert anonymous.status_code == 422
    assert "Sign in first" in anonymous.json()["detail"]

    # Signed in as the addressee, it works.
    authorised = await client.post(
        f"/invitations/{token}/accept", json={}, headers=org["founder"]["headers"]
    )
    assert authorised.status_code == 200


async def test_an_expired_invitation_is_refused(client, org, session):
    token = (await invite(client, org)).json()["token"]

    stored = (await session.execute(select(Invitation))).scalars().first()
    stored.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await session.commit()

    response = await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})
    assert response.status_code == 404
    assert response.json()["detail"] == "This invitation is not valid."


@pytest.mark.parametrize("bad", ["not-a-token", "x" * 43, ""])
async def test_an_invalid_token_is_refused_uniformly(client, org, bad):
    """Unknown, revoked, used and expired all report the same thing, so nobody
    can probe which tokens once existed."""
    response = await client.post(f"/invitations/{bad}/accept", json={"password": PASSWORD})
    assert response.status_code in (404, 405)


# --- revoking --------------------------------------------------------------


async def test_a_revoked_invitation_stops_working(client, org):
    created = await invite(client, org)
    token = created.json()["token"]
    invitation_id = created.json()["invitation"]["id"]

    revoked = await client.delete(
        f"/invitations/{invitation_id}", headers=org["founder"]["headers"]
    )
    assert revoked.status_code == 200

    response = await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})
    assert response.status_code == 404


async def test_an_outsider_cannot_revoke_an_invitation(client, org):
    outsider = await register_account(client, email="outsider2@y.com", org="Y")
    created = await invite(client, org)

    response = await client.delete(
        f"/invitations/{created.json()['invitation']['id']}", headers=outsider["headers"]
    )
    assert response.status_code == 404


async def test_revoking_twice_is_refused(client, org):
    created = await invite(client, org)
    invitation_id = created.json()["invitation"]["id"]

    await client.delete(f"/invitations/{invitation_id}", headers=org["founder"]["headers"])
    again = await client.delete(f"/invitations/{invitation_id}", headers=org["founder"]["headers"])
    assert again.status_code == 409


async def test_an_unknown_invitation_reads_as_absent(client, org):
    response = await client.delete(
        f"/invitations/{uuid.uuid4()}", headers=org["founder"]["headers"]
    )
    assert response.status_code == 404


async def test_stale_invitations_are_reported_as_expired(client, org, session):
    token = (await invite(client, org)).json()["token"]
    _ = token

    stored = (await session.execute(select(Invitation))).scalars().first()
    stored.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    listed = await client.get(
        f"/teams/{org['team_id']}/invitations", headers=org["founder"]["headers"]
    )
    assert listed.json()[0]["status"] == InvitationStatus.EXPIRED.value


async def test_a_token_never_reaches_the_request_log(client, org, caplog):
    """The token is in the URL because an invite link has to be openable, so
    the log is the one place it can be kept out of."""
    import logging

    token = (await invite(client, org)).json()["token"]

    with caplog.at_level(logging.INFO):
        await client.get(f"/invitations/{token}")
        await client.post(f"/invitations/{token}/accept", json={"password": PASSWORD})

    # Only Avocado's own loggers. httpx logs the full request URL client-side,
    # but that is the test harness talking, not the application.
    logged = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("app.")
    )
    assert token not in logged
    assert "[redacted]" in logged


async def test_a_token_never_reaches_an_error_body(client, org):
    """Error responses echo the path, and they end up in trackers and tickets."""
    response = await client.get(f"/invitations/{'z' * 43}")
    assert response.status_code == 404
    assert "z" * 43 not in response.text
    assert response.json()["instance"].endswith("/invitations/[redacted]")
