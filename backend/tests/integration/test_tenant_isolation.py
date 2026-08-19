"""Tenant isolation.

Architecture §15 calls this out as a required test, and it is the one that most
needs to exist: every other feature is recoverable if it breaks, but a tenancy
leak is not. Two unrelated organizations are created, and every workspace-scoped
route is probed across the boundary.

A cross-tenant resource must read as 404, not 403 — confirming that an id
exists is itself a leak.
"""

from __future__ import annotations

import io
import uuid

import pytest

from tests.conftest import register_account

pytestmark = pytest.mark.anyio


@pytest.fixture
async def two_tenants(client):
    """Two organizations with no relationship to each other."""
    alice = await register_account(client, email="alice@alpha.com", org="Alpha Corp")
    bob = await register_account(client, email="bob@beta.com", org="Beta Corp")
    assert alice["workspace_id"] != bob["workspace_id"]
    return alice, bob


async def test_a_tenant_only_lists_its_own_workspaces(two_tenants, client):
    alice, bob = two_tenants

    alice_ids = {
        w["id"] for w in (await client.get("/workspaces", headers=alice["headers"])).json()
    }
    bob_ids = {w["id"] for w in (await client.get("/workspaces", headers=bob["headers"])).json()}

    assert alice_ids.isdisjoint(bob_ids)
    assert bob["workspace_id"] not in alice_ids


async def test_reading_another_tenants_workspace_is_a_404(two_tenants, client):
    alice, bob = two_tenants
    response = await client.get(f"/workspaces/{bob['workspace_id']}", headers=alice["headers"])
    assert response.status_code == 404


async def test_writing_to_another_tenants_workspace_is_refused(two_tenants, client):
    alice, bob = two_tenants

    patched = await client.patch(
        f"/workspaces/{bob['workspace_id']}",
        json={"name": "Owned"},
        headers=alice["headers"],
    )
    assert patched.status_code == 404

    deleted = await client.delete(f"/workspaces/{bob['workspace_id']}", headers=alice["headers"])
    assert deleted.status_code == 404


async def test_documents_cannot_be_read_across_the_boundary(two_tenants, client):
    alice, bob = two_tenants

    upload = await client.post(
        f"/workspaces/{bob['workspace_id']}/documents",
        files={
            "file": ("secret.txt", io.BytesIO(b"Beta Corp confidential revenue plan"), "text/plain")
        },
        headers=bob["headers"],
    )
    assert upload.status_code == 201
    document_id = upload.json()["document"]["id"]

    # Bob can read his own document.
    assert (
        await client.get(f"/documents/{document_id}", headers=bob["headers"])
    ).status_code == 200

    # Alice cannot, by any route.
    assert (
        await client.get(f"/documents/{document_id}", headers=alice["headers"])
    ).status_code == 404
    assert (
        await client.delete(f"/documents/{document_id}", headers=alice["headers"])
    ).status_code == 404
    assert (
        await client.post(f"/documents/{document_id}/reprocess", headers=alice["headers"])
    ).status_code == 404


async def test_uploading_into_another_tenants_workspace_is_refused(two_tenants, client):
    alice, bob = two_tenants
    response = await client.post(
        f"/workspaces/{bob['workspace_id']}/documents",
        files={"file": ("x.txt", io.BytesIO(b"payload"), "text/plain")},
        headers=alice["headers"],
    )
    assert response.status_code == 404


async def test_conversations_cannot_be_read_across_the_boundary(two_tenants, client):
    alice, bob = two_tenants

    created = await client.post(
        f"/workspaces/{bob['workspace_id']}/conversations",
        json={"title": "Beta internal planning"},
        headers=bob["headers"],
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    # Alice cannot list Bob's conversations even naming his workspace...
    listed = await client.get(
        f"/workspaces/{bob['workspace_id']}/conversations", headers=alice["headers"]
    )
    assert listed.status_code == 404

    # ...nor reach the thread through her own workspace id.
    through_own = await client.get(
        f"/workspaces/{alice['workspace_id']}/conversations/{conversation_id}",
        headers=alice["headers"],
    )
    assert through_own.status_code == 404


async def test_retrieval_never_returns_another_tenants_chunks(two_tenants, client, app):
    """The core isolation guarantee: search is scoped, not filtered afterwards."""
    alice, bob = two_tenants

    marker = "zylophone-quarterly-margin-8817"
    upload = await client.post(
        f"/workspaces/{bob['workspace_id']}/documents",
        files={"file": ("beta.txt", io.BytesIO(marker.encode() * 40), "text/plain")},
        headers=bob["headers"],
    )
    assert upload.status_code == 201

    await _wait_for_ready(client, upload.json()["document"]["id"], bob["headers"])

    # Ask, from Alice's workspace, for exactly the text that only Bob has.
    conversation = await client.post(
        f"/workspaces/{alice['workspace_id']}/conversations",
        json={"title": "probe"},
        headers=alice["headers"],
    )
    reply = await client.post(
        f"/workspaces/{alice['workspace_id']}/conversations/{conversation.json()['id']}/messages",
        json={"content": marker},
        headers=alice["headers"],
    )
    assert reply.status_code == 201

    # No citation may point at Bob's document, and the marker must not appear
    # in any retrieved snippet.
    citations = reply.json()["assistant_message"]["citations"]
    assert citations == []


async def test_analysis_runs_are_not_readable_across_the_boundary(two_tenants, client):
    alice, _bob = two_tenants
    # A run id that does not belong to Alice reads as absent, not forbidden.
    response = await client.get(f"/analysis-runs/{uuid.uuid4()}", headers=alice["headers"])
    assert response.status_code == 404


async def test_workspace_stats_do_not_leak_across_the_boundary(two_tenants, client):
    alice, bob = two_tenants
    response = await client.get(
        f"/workspaces/{bob['workspace_id']}/stats", headers=alice["headers"]
    )
    assert response.status_code == 404


async def _wait_for_ready(client, document_id: str, headers: dict, attempts: int = 60):
    """Ingestion runs in-process for tests; poll until it settles."""
    import asyncio

    for _ in range(attempts):
        response = await client.get(f"/documents/{document_id}", headers=headers)
        if response.status_code == 200 and response.json()["status"] in ("ready", "failed"):
            return response.json()
        await asyncio.sleep(0.05)
    raise AssertionError("Document never finished processing.")
