"""Role-based access control.

Roles only mean something if they are enforced, and the failure mode is silent:
a missing check looks exactly like a passing one until someone exploits it. So
every privileged route is probed from every role below it.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import Role
from tests.conftest import register_account

pytestmark = pytest.mark.anyio


async def invite_and_accept(client, host, team_id, email, role: Role) -> dict:
    """Add a second person to `host`'s org at a given role."""
    created = await client.post(
        f"/teams/{team_id}/invitations",
        json={"email": email, "role": role.value},
        headers=host["headers"],
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]

    accepted = await client.post(
        f"/invitations/{token}/accept",
        json={"password": "correct-horse-battery-staple", "full_name": "Invited"},
    )
    assert accepted.status_code == 200, accepted.text
    tokens = accepted.json()
    return {"email": email, "headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


@pytest.fixture
async def org(client):
    """An organization whose founder is its org admin, plus its default team."""
    founder = await register_account(client, email="founder@acme.com", org="Acme")
    teams = await client.get("/teams", headers=founder["headers"])
    assert teams.status_code == 200
    return {"founder": founder, "team_id": teams.json()[0]["id"]}


# --- role hierarchy --------------------------------------------------------


def test_role_ranks_are_ordered():
    assert Role.ORG_ADMIN.at_least(Role.TEAM_ADMIN)
    assert Role.TEAM_ADMIN.at_least(Role.MEMBER)
    assert Role.MEMBER.at_least(Role.VIEWER)
    assert not Role.VIEWER.at_least(Role.MEMBER)
    assert not Role.MEMBER.at_least(Role.TEAM_ADMIN)


async def test_a_lower_membership_row_does_not_mask_org_admin(client, org):
    """An org admin recorded at a lower role on some other team keeps org-wide
    standing there — the strongest applicable role wins, not the membership."""
    founder_id = (await client.get("/auth/me", headers=org["founder"]["headers"])).json()["id"]

    # A second team, where the founder is deliberately recorded as a viewer
    # while remaining an org admin via their membership on the first team.
    created = await client.post(
        "/teams", json={"name": "Side project"}, headers=org["founder"]["headers"]
    )
    second_team = created.json()["id"]

    demoted = await client.patch(
        f"/teams/{second_team}/members/{founder_id}",
        json={"role": "viewer"},
        headers=org["founder"]["headers"],
    )
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "viewer"

    # The membership row says viewer, but org-wide standing outranks it.
    team = await client.get(f"/teams/{second_team}", headers=org["founder"]["headers"])
    assert team.json()["your_role"] == "org_admin"

    # And the org-admin powers genuinely still work there.
    renamed = await client.patch(
        f"/teams/{second_team}",
        json={"name": "Renamed anyway"},
        headers=org["founder"]["headers"],
    )
    assert renamed.status_code == 200


async def test_the_founder_is_an_org_admin(client, org):
    team = await client.get(f"/teams/{org['team_id']}", headers=org["founder"]["headers"])
    assert team.status_code == 200
    assert team.json()["your_role"] == "org_admin"


# --- team administration ---------------------------------------------------


async def test_only_an_org_admin_can_create_a_team(client, org):
    member = await invite_and_accept(
        client, org["founder"], org["team_id"], "member@acme.com", Role.MEMBER
    )

    refused = await client.post("/teams", json={"name": "Skunkworks"}, headers=member["headers"])
    assert refused.status_code == 403

    allowed = await client.post(
        "/teams", json={"name": "Skunkworks"}, headers=org["founder"]["headers"]
    )
    assert allowed.status_code == 201
    # The creator joins as team_admin, but org-wide standing outranks the
    # membership row, so their effective role here is org_admin.
    assert allowed.json()["your_role"] == "org_admin"


async def test_a_member_cannot_rename_or_delete_a_team(client, org):
    member = await invite_and_accept(
        client, org["founder"], org["team_id"], "m2@acme.com", Role.MEMBER
    )

    renamed = await client.patch(
        f"/teams/{org['team_id']}", json={"name": "Renamed"}, headers=member["headers"]
    )
    assert renamed.status_code == 403

    deleted = await client.delete(f"/teams/{org['team_id']}", headers=member["headers"])
    assert deleted.status_code == 403


async def test_a_team_admin_can_rename_but_not_delete(client, org):
    """Deleting a team destroys its workspaces, so it stays with the org admin."""
    admin = await invite_and_accept(
        client, org["founder"], org["team_id"], "ta@acme.com", Role.TEAM_ADMIN
    )

    renamed = await client.patch(
        f"/teams/{org['team_id']}",
        json={"name": "Renamed by team admin"},
        headers=admin["headers"],
    )
    assert renamed.status_code == 200

    deleted = await client.delete(f"/teams/{org['team_id']}", headers=admin["headers"])
    assert deleted.status_code == 403


async def test_a_team_with_workspaces_cannot_be_deleted(client, org):
    """Cascading away every document in a team is too much to do by accident."""
    response = await client.delete(f"/teams/{org['team_id']}", headers=org["founder"]["headers"])
    assert response.status_code == 409
    assert "workspace" in response.json()["detail"]


async def test_an_empty_team_can_be_deleted(client, org):
    created = await client.post(
        "/teams", json={"name": "Temporary"}, headers=org["founder"]["headers"]
    )
    team_id = created.json()["id"]

    deleted = await client.delete(f"/teams/{team_id}", headers=org["founder"]["headers"])
    assert deleted.status_code == 200
    assert (
        await client.get(f"/teams/{team_id}", headers=org["founder"]["headers"])
    ).status_code == 404


# --- membership ------------------------------------------------------------


async def test_a_member_cannot_change_roles(client, org):
    member = await invite_and_accept(
        client, org["founder"], org["team_id"], "m3@acme.com", Role.MEMBER
    )
    members = await client.get(
        f"/teams/{org['team_id']}/members", headers=org["founder"]["headers"]
    )
    target = next(m for m in members.json() if m["email"] == "m3@acme.com")

    response = await client.patch(
        f"/teams/{org['team_id']}/members/{target['user_id']}",
        json={"role": "team_admin"},
        headers=member["headers"],
    )
    assert response.status_code == 403


async def test_nobody_can_grant_a_role_above_their_own(client, org):
    """Otherwise a team admin promotes themselves and the hierarchy is decorative."""
    admin = await invite_and_accept(
        client, org["founder"], org["team_id"], "ta2@acme.com", Role.TEAM_ADMIN
    )
    member = await invite_and_accept(
        client, org["founder"], org["team_id"], "m4@acme.com", Role.MEMBER
    )
    _ = member

    members = await client.get(
        f"/teams/{org['team_id']}/members", headers=org["founder"]["headers"]
    )
    target = next(m for m in members.json() if m["email"] == "m4@acme.com")

    escalation = await client.patch(
        f"/teams/{org['team_id']}/members/{target['user_id']}",
        json={"role": "org_admin"},
        headers=admin["headers"],
    )
    assert escalation.status_code == 403
    assert "above your own" in escalation.json()["detail"]

    # The same admin may grant a role at or below their own.
    allowed = await client.patch(
        f"/teams/{org['team_id']}/members/{target['user_id']}",
        json={"role": "team_admin"},
        headers=admin["headers"],
    )
    assert allowed.status_code == 200


async def test_the_last_org_admin_cannot_be_demoted(client, org):
    """An organization with no admin cannot invite, promote, or recover."""
    founder_id = (await client.get("/auth/me", headers=org["founder"]["headers"])).json()["id"]

    response = await client.patch(
        f"/teams/{org['team_id']}/members/{founder_id}",
        json={"role": "member"},
        headers=org["founder"]["headers"],
    )
    assert response.status_code == 422
    assert "only administrator" in response.json()["detail"]


async def test_the_last_org_admin_cannot_leave(client, org):
    founder_id = (await client.get("/auth/me", headers=org["founder"]["headers"])).json()["id"]

    response = await client.delete(
        f"/teams/{org['team_id']}/members/{founder_id}", headers=org["founder"]["headers"]
    )
    assert response.status_code == 422


async def test_an_admin_can_be_demoted_once_another_exists(client, org):
    await invite_and_accept(
        client, org["founder"], org["team_id"], "second-admin@acme.com", Role.ORG_ADMIN
    )
    founder_id = (await client.get("/auth/me", headers=org["founder"]["headers"])).json()["id"]

    response = await client.patch(
        f"/teams/{org['team_id']}/members/{founder_id}",
        json={"role": "member"},
        headers=org["founder"]["headers"],
    )
    assert response.status_code == 200
    assert response.json()["role"] == "member"


async def test_anyone_can_leave_a_team_themselves(client, org):
    await invite_and_accept(
        client, org["founder"], org["team_id"], "other-admin@acme.com", Role.ORG_ADMIN
    )
    member = await invite_and_accept(
        client, org["founder"], org["team_id"], "leaver@acme.com", Role.MEMBER
    )
    member_id = (await client.get("/auth/me", headers=member["headers"])).json()["id"]

    # No admin privilege needed to remove yourself.
    response = await client.delete(
        f"/teams/{org['team_id']}/members/{member_id}", headers=member["headers"]
    )
    assert response.status_code == 200


async def test_an_org_admin_administers_a_team_without_joining_it(client, org):
    """org_admin is organization-wide; requiring a membership row in every team
    would wrongly refuse them."""
    created = await client.post(
        "/teams", json={"name": "Others"}, headers=org["founder"]["headers"]
    )
    team_id = created.json()["id"]

    # Remove the founder's own membership, leaving an admin with no row here.
    founder_id = (await client.get("/auth/me", headers=org["founder"]["headers"])).json()["id"]
    await client.delete(f"/teams/{team_id}/members/{founder_id}", headers=org["founder"]["headers"])

    response = await client.patch(
        f"/teams/{team_id}",
        json={"name": "Still administrable"},
        headers=org["founder"]["headers"],
    )
    assert response.status_code == 200


# --- organization ----------------------------------------------------------


async def test_only_an_org_admin_can_rename_the_organization(client, org):
    member = await invite_and_accept(
        client, org["founder"], org["team_id"], "m5@acme.com", Role.MEMBER
    )

    assert (
        await client.patch(
            "/organizations/current", json={"name": "Hijacked"}, headers=member["headers"]
        )
    ).status_code == 403
    assert (
        await client.patch(
            "/organizations/current",
            json={"name": "Acme Corp"},
            headers=org["founder"]["headers"],
        )
    ).status_code == 200


async def test_the_member_directory_lists_each_person_once(client, org):
    """Somebody on several teams is one person, shown at their strongest role."""
    await invite_and_accept(client, org["founder"], org["team_id"], "multi@acme.com", Role.MEMBER)
    second = await client.post("/teams", json={"name": "Second"}, headers=org["founder"]["headers"])
    await invite_and_accept(
        client, org["founder"], second.json()["id"], "multi2@acme.com", Role.TEAM_ADMIN
    )

    members = await client.get("/organizations/current/members", headers=org["founder"]["headers"])
    assert members.status_code == 200
    emails = [m["email"] for m in members.json()]
    assert len(emails) == len(set(emails))


# --- cross-tenant ----------------------------------------------------------


async def test_a_team_in_another_organization_reads_as_absent(client, org):
    """404, not 403 — confirming an id exists is itself a leak."""
    outsider = await register_account(client, email="outsider@other.com", org="Other")

    assert (
        await client.get(f"/teams/{org['team_id']}", headers=outsider["headers"])
    ).status_code == 404
    assert (
        await client.get(f"/teams/{org['team_id']}/members", headers=outsider["headers"])
    ).status_code == 404
    assert (
        await client.patch(
            f"/teams/{org['team_id']}", json={"name": "x"}, headers=outsider["headers"]
        )
    ).status_code == 404


async def test_teams_are_not_listed_across_organizations(client, org):
    outsider = await register_account(client, email="outsider2@other.com", org="Other Two")
    listed = await client.get("/teams", headers=outsider["headers"])
    assert org["team_id"] not in [t["id"] for t in listed.json()]


async def test_an_unknown_team_reads_as_absent(client, org):
    response = await client.get(f"/teams/{uuid.uuid4()}", headers=org["founder"]["headers"])
    assert response.status_code == 404


async def test_team_routes_require_authentication(client, org):
    for method, path in [
        ("get", "/teams"),
        ("post", "/teams"),
        ("get", f"/teams/{org['team_id']}"),
        ("get", "/organizations/current"),
        ("get", "/organizations/current/members"),
    ]:
        response = await getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
        assert response.status_code == 401, path
