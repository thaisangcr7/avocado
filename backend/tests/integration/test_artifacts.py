"""Artifacts: creation, versioning, download, and tenant isolation."""

from __future__ import annotations

import pytest

from tests.conftest import register_account

pytestmark = pytest.mark.anyio


DASHBOARD = "<html><body><h1>Q3</h1><script>console.log(1)</script></body></html>"


async def create(client, account, **overrides):
    payload = {
        "title": "Q3 dashboard",
        "filename": "q3.html",
        "kind": "html",
        "content": DASHBOARD,
    }
    payload.update(overrides)
    return await client.post(
        f"/workspaces/{account['workspace_id']}/artifacts",
        json=payload,
        headers=account["headers"],
    )


async def test_an_artifact_starts_at_version_one(client, account):
    response = await create(client, account)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["version"] == 1
    assert body["author"] == "user"
    # A first version roots its own lineage, so "newest of each" stays a
    # group-by rather than a walk up parent pointers.
    assert body["lineage_id"] == body["id"]


async def test_revising_appends_a_version_and_keeps_the_old_one(client, account):
    first = (await create(client, account)).json()

    revised = await client.post(
        f"/workspaces/{account['workspace_id']}/artifacts/{first['id']}/versions",
        json={"content": "<html><body><h1>Q3 revised</h1></body></html>"},
        headers=account["headers"],
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["version"] == 2
    assert revised.json()["lineage_id"] == first["lineage_id"]

    # The earlier version is still readable, not overwritten.
    original = await client.get(
        f"/workspaces/{account['workspace_id']}/artifacts/{first['id']}",
        headers=account["headers"],
    )
    assert original.status_code == 200
    assert "Q3 revised" not in original.json()["content"]
    assert [v["version"] for v in original.json()["versions"]] == [1, 2]


async def test_an_omitted_title_carries_forward(client, account):
    """Most edits change the body only; leaving the title out must not clear it."""
    first = (await create(client, account, title="Keep me")).json()
    revised = await client.post(
        f"/workspaces/{account['workspace_id']}/artifacts/{first['id']}/versions",
        json={"content": "<html><body>new</body></html>"},
        headers=account["headers"],
    )
    assert revised.json()["title"] == "Keep me"


async def test_the_list_shows_one_row_per_artifact_at_its_newest(client, account):
    first = (await create(client, account)).json()
    for body in ("<html>v2</html>", "<html>v3</html>"):
        await client.post(
            f"/workspaces/{account['workspace_id']}/artifacts/{first['id']}/versions",
            json={"content": body},
            headers=account["headers"],
        )

    listed = await client.get(
        f"/workspaces/{account['workspace_id']}/artifacts", headers=account["headers"]
    )
    assert listed.status_code == 200
    rows = [r for r in listed.json() if r["lineage_id"] == first["lineage_id"]]
    assert len(rows) == 1, "three versions must not become three rows"
    assert rows[0]["version"] == 3


async def test_html_never_downloads_as_html(client, account):
    """Model-written markup served inline would run its script on this origin.

    The viewer renders it in a sandboxed, null-origin frame instead; the
    download path hands over bytes and nothing else.
    """
    artifact = (await create(client, account)).json()
    response = await client.get(
        f"/workspaces/{account['workspace_id']}/artifacts/{artifact['id']}/download",
        headers=account["headers"],
    )
    assert response.status_code == 200
    assert "text/html" not in response.headers["content-type"]
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_an_oversized_artifact_is_refused(client, account):
    response = await create(client, account, content="x" * 600_000)
    assert response.status_code == 422


async def test_artifacts_do_not_cross_tenants(client):
    alice = await register_account(client, email="alice-art@example.com", org="Alice Co")
    bob = await register_account(client, email="bob-art@example.com", org="Bob Co")

    artifact = (await create(client, alice)).json()

    # Bob cannot read it through his own workspace, nor through Alice's.
    through_own = await client.get(
        f"/workspaces/{bob['workspace_id']}/artifacts/{artifact['id']}",
        headers=bob["headers"],
    )
    assert through_own.status_code == 404

    through_hers = await client.get(
        f"/workspaces/{alice['workspace_id']}/artifacts/{artifact['id']}",
        headers=bob["headers"],
    )
    assert through_hers.status_code == 404

    listed = await client.get(
        f"/workspaces/{bob['workspace_id']}/artifacts", headers=bob["headers"]
    )
    assert listed.json() == []


async def test_revising_another_tenants_artifact_is_refused(client):
    alice = await register_account(client, email="alice-rev@example.com", org="Alice Co")
    bob = await register_account(client, email="bob-rev@example.com", org="Bob Co")
    artifact = (await create(client, alice)).json()

    response = await client.post(
        f"/workspaces/{bob['workspace_id']}/artifacts/{artifact['id']}/versions",
        json={"content": "<html>owned</html>"},
        headers=bob["headers"],
    )
    assert response.status_code == 404


async def test_artifacts_require_authentication(client, account):
    artifact = (await create(client, account)).json()
    assert (await client.get(f"/workspaces/{account['workspace_id']}/artifacts")).status_code == 401
    assert (
        await client.get(f"/workspaces/{account['workspace_id']}/artifacts/{artifact['id']}")
    ).status_code == 401


# --- model-authored artifacts ----------------------------------------------


DRAFT = {
    "title": "Q3 revenue dashboard",
    "filename": "q3-revenue.html",
    "kind": "html",
    "content": "<html><body><h1>Q3</h1></body></html>",
}


async def test_the_model_can_author_a_document(client, account, fake_llm):
    import json

    fake_llm.responses = [json.dumps(DRAFT)]
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/artifacts/generate",
        json={"instruction": "Build a dashboard of Q3 revenue by region."},
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["title"] == DRAFT["title"]
    assert body["author"] == "ai", "a document the model wrote is not authored by the user"
    assert body["version"] == 1
    assert body["model_used"]


async def test_generate_is_not_read_as_an_artifact_id(client, account, fake_llm):
    """`/artifacts/generate` sits under the same prefix as `/artifacts/{id}`.

    Declared the wrong way round, "generate" parses as an id and the route
    404s instead of generating — a failure that only shows up at runtime.
    """
    import json

    fake_llm.responses = [json.dumps(DRAFT)]
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/artifacts/generate",
        json={"instruction": "anything at all"},
        headers=account["headers"],
    )
    assert response.status_code != 404


async def test_an_unusable_draft_is_an_error_not_a_silent_pass(client, account, fake_llm):
    """The user asked for this explicitly, so failure has to be visible."""
    fake_llm.responses = ["not json at all"]
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/artifacts/generate",
        json={"instruction": "Build something."},
        headers=account["headers"],
    )
    assert response.status_code == 502
