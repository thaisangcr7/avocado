"""Presets: visibility, permission, and the tenant boundary.

The interesting rules are all about who sees what. A preset is a system prompt
— the most sensitive thing a team writes into this product — so "someone else's
private preset is invisible" and "a share cannot cross a tenant" are the
properties worth protecting, not the CRUD.
"""

from __future__ import annotations

import pytest

from app.models.enums import Role
from tests.conftest import register_account
from tests.integration.test_rbac import invite_and_accept

pytestmark = pytest.mark.anyio

PROMPT = "You are a careful reviewer. Prefer specifics over praise."


async def whoami(client, account) -> dict:
    return (await client.get("/auth/me", headers=account["headers"])).json()


@pytest.fixture
async def company(client):
    """A founder and two colleagues in one organisation.

    Registering twice makes two organisations, not two colleagues — which is
    the whole point of the tenant boundary, and useless for testing what people
    inside one org can see of each other.
    """
    founder = await register_account(client, email="founder@acme.example", org="Acme")
    teams = await client.get("/teams", headers=founder["headers"])
    team_id = teams.json()[0]["id"]
    colleague = await invite_and_accept(
        client, founder, team_id, "colleague@acme.example", Role.TEAM_ADMIN
    )
    bystander = await invite_and_accept(
        client, founder, team_id, "bystander@acme.example", Role.MEMBER
    )
    return {"founder": founder, "colleague": colleague, "bystander": bystander}


async def make_preset(client, account, **overrides) -> dict:
    body = {"name": "Sage", "system_prompt": PROMPT, **overrides}
    response = await client.post("/presets", json=body, headers=account["headers"])
    assert response.status_code == 201, response.text
    return response.json()


# --- the basics -----------------------------------------------------------


async def test_a_preset_gets_a_slash_command_from_its_name(client, account):
    preset = await make_preset(client, account, name="Code Review Buddy")

    assert preset["slug"] == "code-review-buddy"
    assert preset["version"] == 1
    assert preset["is_mine"] is True
    assert preset["can_edit"] is True


async def test_a_second_preset_of_the_same_name_gets_its_own_command(client, account):
    """Two people naming a preset "Sage" is ordinary, not an error."""
    first = await make_preset(client, account)
    second = await make_preset(client, account)

    assert first["slug"] == "sage"
    assert second["slug"] == "sage-2"


async def test_a_slash_command_asked_for_by_name_and_already_taken_is_a_conflict(client, account):
    """A derived slug steps aside quietly; one the caller chose must not."""
    await make_preset(client, account, slug="sage")

    response = await client.post(
        "/presets",
        json={"name": "Other", "system_prompt": PROMPT, "slug": "sage"},
        headers=account["headers"],
    )

    assert response.status_code == 409


async def test_an_empty_instruction_is_refused(client, account):
    response = await client.post(
        "/presets",
        json={"name": "Blank", "system_prompt": "   "},
        headers=account["headers"],
    )

    assert response.status_code == 422


async def test_editing_bumps_the_version(client, account):
    preset = await make_preset(client, account)

    updated = await client.patch(
        f"/presets/{preset['id']}",
        json={"system_prompt": "Something else entirely."},
        headers=account["headers"],
    )

    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["system_prompt"] == "Something else entirely."


# --- who sees what --------------------------------------------------------


async def test_a_private_preset_is_invisible_to_a_colleague(client, company):
    """Same organisation is not the same as shared."""
    account, colleague = company["founder"], company["colleague"]
    mine = await make_preset(client, account)

    listed = (await client.get("/presets", headers=colleague["headers"])).json()
    assert [p["id"] for p in listed["presets"]] == []

    # And not reachable by id either. 404 rather than 403: confirming the id
    # exists is itself something they should not learn.
    direct = await client.get(f"/presets/{mine['id']}", headers=colleague["headers"])
    assert direct.status_code == 404


async def test_a_shared_preset_reaches_exactly_the_person_named(client, company):
    account, colleague, bystander = (
        company["founder"],
        company["colleague"],
        company["bystander"],
    )
    preset = await make_preset(client, account)

    shared = await client.post(
        f"/presets/{preset['id']}/share",
        json={"user_id": (await whoami(client, colleague))["id"]},
        headers=account["headers"],
    )
    assert shared.status_code == 200

    theirs = (await client.get("/presets?which=shared", headers=colleague["headers"])).json()
    assert [p["slug"] for p in theirs["presets"]] == ["sage"]
    # A share is to one person, not to the room.
    others = (await client.get("/presets", headers=bystander["headers"])).json()
    assert others["presets"] == []


async def test_a_shared_preset_cannot_be_edited_by_the_recipient(client, company):
    account, colleague = company["founder"], company["colleague"]
    preset = await make_preset(client, account)
    await client.post(
        f"/presets/{preset['id']}/share",
        json={"user_id": (await whoami(client, colleague))["id"]},
        headers=account["headers"],
    )

    response = await client.patch(
        f"/presets/{preset['id']}",
        json={"name": "Mine now"},
        headers=colleague["headers"],
    )

    assert response.status_code == 403


async def test_publishing_shows_a_preset_to_the_organisation(client, company):
    account, colleague = company["founder"], company["colleague"]
    preset = await make_preset(client, account)

    published = await client.post(f"/presets/{preset['id']}/publish", headers=account["headers"])
    assert published.status_code == 200, published.text
    assert published.json()["scope"] == "published"

    listed = (await client.get("/presets?which=community", headers=colleague["headers"])).json()
    assert [p["slug"] for p in listed["presets"]] == ["sage"]


# --- the tenant boundary --------------------------------------------------


async def test_a_preset_never_leaves_its_organisation(client):
    """The isolation test AGENTS.md requires for a new scoped path."""
    acme = await register_account(client, email="a@acme.example", org="Acme")
    other = await register_account(client, email="b@other.example", org="Other Co")

    preset = await make_preset(client, acme, scope="private")
    await client.post(f"/presets/{preset['id']}/publish", headers=acme["headers"])

    # Published is org-wide, not world-wide.
    listed = (await client.get("/presets", headers=other["headers"])).json()
    assert listed["presets"] == []
    assert (
        await client.get(f"/presets/{preset['id']}", headers=other["headers"])
    ).status_code == 404


async def test_a_preset_cannot_be_shared_into_another_tenant(client):
    """The one operation that names another user by id."""
    acme = await register_account(client, email="owner@acme.example", org="Acme")
    outsider = await register_account(client, email="outsider@other.example", org="Other Co")
    preset = await make_preset(client, acme)

    response = await client.post(
        f"/presets/{preset['id']}/share",
        json={"user_id": (await whoami(client, outsider))["id"]},
        headers=acme["headers"],
    )

    assert response.status_code == 404, "an id alone must not carry a prompt across tenants"
    assert (await client.get("/presets", headers=outsider["headers"])).json()["presets"] == []


async def test_a_stranger_cannot_edit_or_delete(client):
    acme = await register_account(client, email="owner2@acme.example", org="Acme")
    outsider = await register_account(client, email="outsider2@other.example", org="Other Co")
    preset = await make_preset(client, acme)

    assert (
        await client.patch(
            f"/presets/{preset['id']}", json={"name": "x"}, headers=outsider["headers"]
        )
    ).status_code == 404
    assert (
        await client.delete(f"/presets/{preset['id']}", headers=outsider["headers"])
    ).status_code == 404


# --- pinning --------------------------------------------------------------


async def test_pinning_is_personal(client, company):
    account, colleague = company["founder"], company["colleague"]
    preset = await make_preset(client, account)
    await client.post(f"/presets/{preset['id']}/publish", headers=account["headers"])

    pinned = await client.put(f"/presets/{preset['id']}/pin", headers=account["headers"])
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True

    # One person's shortcut is not a property of everyone's copy.
    theirs = (await client.get("/presets", headers=colleague["headers"])).json()
    assert theirs["presets"][0]["pinned"] is False

    mine = (await client.get("/presets?which=pinned", headers=account["headers"])).json()
    assert [p["slug"] for p in mine["presets"]] == ["sage"]


async def test_unpinning_removes_it_from_the_tab(client, account):
    preset = await make_preset(client, account)
    await client.put(f"/presets/{preset['id']}/pin", headers=account["headers"])

    await client.delete(f"/presets/{preset['id']}/pin", headers=account["headers"])

    listed = (await client.get("/presets?which=pinned", headers=account["headers"])).json()
    assert listed["presets"] == []


# --- search ---------------------------------------------------------------


async def test_search_matches_name_slug_and_description(client, account):
    await make_preset(client, account, name="Dockerfile Improvement")
    await make_preset(client, account, name="Sage", description="A patient reviewer")

    by_name = (await client.get("/presets?search=docker", headers=account["headers"])).json()
    assert [p["slug"] for p in by_name["presets"]] == ["dockerfile-improvement"]

    by_description = (
        await client.get("/presets?search=patient", headers=account["headers"])
    ).json()
    assert [p["slug"] for p in by_description["presets"]] == ["sage"]
