"""Workspace lifecycle, role enforcement, and the model catalogue."""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import register_account

pytestmark = pytest.mark.anyio


async def test_registration_creates_exactly_one_default_workspace(client, account):
    response = await client.get("/workspaces", headers=account["headers"])
    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) == 1
    assert workspaces[0]["name"] == "My Workspace"
    # Null preferred_model means Auto.
    assert workspaces[0]["preferred_model"] is None
    assert workspaces[0]["require_grounding"] is True


async def test_a_workspace_can_be_created_read_updated_and_deleted(client, account):
    created = await client.post(
        "/workspaces",
        json={"name": "Finance", "description": "Budget documents"},
        headers=account["headers"],
    )
    assert created.status_code == 201
    workspace_id = created.json()["id"]

    fetched = await client.get(f"/workspaces/{workspace_id}", headers=account["headers"])
    assert fetched.json()["name"] == "Finance"

    updated = await client.patch(
        f"/workspaces/{workspace_id}",
        json={
            "name": "Finance & Ops",
            "preferred_model": "fake-fast",
            "require_grounding": False,
        },
        headers=account["headers"],
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Finance & Ops"
    assert updated.json()["preferred_model"] == "fake-fast"
    assert updated.json()["require_grounding"] is False

    deleted = await client.delete(f"/workspaces/{workspace_id}", headers=account["headers"])
    assert deleted.status_code == 200
    assert (
        await client.get(f"/workspaces/{workspace_id}", headers=account["headers"])
    ).status_code == 404


async def test_a_partial_update_leaves_other_fields_alone(client, account):
    created = await client.post(
        "/workspaces",
        json={"name": "Original", "description": "Keep me"},
        headers=account["headers"],
    )
    workspace_id = created.json()["id"]

    updated = await client.patch(
        f"/workspaces/{workspace_id}", json={"name": "Renamed"}, headers=account["headers"]
    )
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["description"] == "Keep me"


async def test_pinning_a_model_makes_every_request_use_it(client, account, fake_llm):
    """A chosen model is a contract, not a hint (architecture §10)."""
    import io

    from tests.integration.test_documents import upload, wait_for_ready

    workspace_id = account["workspace_id"]
    await client.patch(
        f"/workspaces/{workspace_id}",
        json={"preferred_model": "fake-fast"},
        headers=account["headers"],
    )

    response = await client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("p.txt", io.BytesIO(b"policy content here " * 30), "text/plain")},
        headers=account["headers"],
    )
    await wait_for_ready(client, response.json()["document"]["id"], account["headers"])

    conversation = await client.post(
        f"/workspaces/{workspace_id}/conversations", json={}, headers=account["headers"]
    )
    reply = await client.post(
        f"/workspaces/{workspace_id}/conversations/{conversation.json()['id']}/messages",
        json={"content": "policy content"},
        headers=account["headers"],
    )

    # Even though synthesis would route to the frontier tier under Auto.
    assert reply.json()["assistant_message"]["model_used"] == "fake-fast"
    assert upload  # imported for the helper's side effects in other tests


async def test_creating_a_workspace_in_another_teams_id_is_refused(client, account):
    response = await client.post(
        "/workspaces",
        json={"name": "Intruder", "team_id": str(uuid.uuid4())},
        headers=account["headers"],
    )
    assert response.status_code in (403, 404)


async def test_a_nonexistent_workspace_reads_as_not_found(client, account):
    response = await client.get(f"/workspaces/{uuid.uuid4()}", headers=account["headers"])
    assert response.status_code == 404


async def test_an_invalid_uuid_is_a_validation_error(client, account):
    response = await client.get("/workspaces/not-a-uuid", headers=account["headers"])
    assert response.status_code == 422


async def test_a_workspace_name_is_required(client, account):
    response = await client.post("/workspaces", json={"name": ""}, headers=account["headers"])
    assert response.status_code == 422


async def test_two_organizations_have_separate_default_workspaces(client):
    first = await register_account(client, email="one@first.com", org="First")
    second = await register_account(client, email="two@second.com", org="Second")
    assert first["workspace_id"] != second["workspace_id"]


async def test_the_model_catalogue_lists_selectable_models(client, account):
    response = await client.get("/models", headers=account["headers"])
    assert response.status_code == 200
    catalog = response.json()

    assert catalog["auto_available"] is True
    ids = {m["id"] for m in catalog["models"]}
    assert {"fake-frontier", "fake-fast"} <= ids

    # Everything the picker needs to render a choice.
    model = catalog["models"][0]
    assert {"display_name", "context_window", "input_cost_per_mtok", "tier"} <= model.keys()


async def test_the_model_catalogue_requires_authentication(client):
    assert (await client.get("/models")).status_code == 401
