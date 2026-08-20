"""Proactive suggestions.

§5 is explicit that these are a digest, not a record — nothing is persisted.
The facts are computed exactly; a model only phrases them, and the response
says which happened.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import register_account
from tests.integration.test_task_visibility import make_project, make_task

pytestmark = pytest.mark.anyio


@pytest.fixture
async def owner(client):
    return await register_account(client, email="owner@acme.com", org="Acme")


async def suggestions(client, account, refresh=True):
    response = await client.get(
        f"/workspaces/{account['workspace_id']}/suggestions?refresh={str(refresh).lower()}",
        headers=account["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


async def my_id(client, account):
    return (await client.get("/auth/me", headers=account["headers"])).json()["id"]


async def test_an_empty_workspace_suggests_nothing(client, owner):
    body = await suggestions(client, owner)
    assert body["items"] == []
    assert body["cached"] is False


async def test_an_overdue_task_is_surfaced_first(client, owner, fake_llm):
    """Overdue work outranks everything; a new document must never bury it."""
    # Deterministic phrasing keeps the assertion about ordering, not wording.
    fake_llm.responses = [""]

    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)

    overdue = await make_task(
        client, owner, owner["workspace_id"], project["id"], "Overdue thing", user_id
    )
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{overdue['id']}",
        json={"due_date": (date.today() - timedelta(days=2)).isoformat()},
        headers=owner["headers"],
    )

    body = await suggestions(client, owner)
    kinds = [s["kind"] for s in body["items"]]
    assert "task_overdue" in kinds
    assert kinds[0] == "task_overdue"

    top = body["items"][0]
    assert top["task_id"] == overdue["id"]
    assert top["project_id"] == project["id"]


async def test_a_task_due_soon_is_surfaced(client, owner, fake_llm):
    fake_llm.responses = [""]
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)

    task = await make_task(client, owner, owner["workspace_id"], project["id"], "Due soon", user_id)
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"due_date": (date.today() + timedelta(days=1)).isoformat()},
        headers=owner["headers"],
    )

    kinds = [s["kind"] for s in (await suggestions(client, owner))["items"]]
    assert "task_due" in kinds


async def test_a_distant_deadline_is_not_nagged_about(client, owner, fake_llm):
    fake_llm.responses = [""]
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)

    task = await make_task(client, owner, owner["workspace_id"], project["id"], "Later", user_id)
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"due_date": (date.today() + timedelta(days=60)).isoformat()},
        headers=owner["headers"],
    )

    assert (await suggestions(client, owner))["items"] == []


async def test_a_completed_task_stops_being_suggested(client, owner, fake_llm):
    fake_llm.responses = ["", ""]
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)

    task = await make_task(
        client, owner, owner["workspace_id"], project["id"], "Finish me", user_id
    )
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"due_date": date.today().isoformat()},
        headers=owner["headers"],
    )
    assert (await suggestions(client, owner))["items"]

    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"status": "done"},
        headers=owner["headers"],
    )
    assert (await suggestions(client, owner))["items"] == []


async def test_a_blocked_task_is_surfaced(client, owner, fake_llm):
    fake_llm.responses = [""]
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)

    task = await make_task(client, owner, owner["workspace_id"], project["id"], "Stuck", user_id)
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"status": "blocked"},
        headers=owner["headers"],
    )

    kinds = [s["kind"] for s in (await suggestions(client, owner))["items"]]
    assert "task_blocked" in kinds


async def test_somebody_elses_task_is_not_your_nudge(client, owner, fake_llm):
    """Suggestions are personal; another person's deadline is not yours."""
    from app.models.enums import Role
    from tests.integration.test_rbac import invite_and_accept

    fake_llm.responses = [""]
    teams = await client.get("/teams", headers=owner["headers"])
    other = await invite_and_accept(
        client, owner, teams.json()[0]["id"], "other@acme.com", Role.MEMBER
    )
    # They joined the owner's team, so they share the same workspace.
    other["workspace_id"] = owner["workspace_id"]
    other_id = await my_id(client, other)

    project = await make_project(client, owner, owner["workspace_id"], "P")
    task = await make_task(client, owner, owner["workspace_id"], project["id"], "Theirs", other_id)
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"due_date": date.today().isoformat()},
        headers=owner["headers"],
    )

    mine = [s["title"] for s in (await suggestions(client, owner))["items"]]
    assert not any("Theirs" in title for title in mine)

    fake_llm.responses = [""]
    theirs = [s["title"] for s in (await suggestions(client, other))["items"]]
    assert any("Theirs" in title for title in theirs)


async def test_a_failed_document_is_reported_to_its_uploader(client, owner, fake_llm):
    """A failed document is invisible to retrieval, so its uploader needs
    telling rather than left wondering why answers are missing."""
    import io

    fake_llm.responses = [""]
    await client.post(
        f"/workspaces/{owner['workspace_id']}/documents",
        files={"file": ("broken.csv", io.BytesIO(b"a,b\n"), "text/csv")},
        headers=owner["headers"],
    )

    # An empty CSV fails ingestion; give the in-process job a moment.
    import asyncio

    for _ in range(40):
        body = await suggestions(client, owner)
        if any(s["kind"] == "failed_document" for s in body["items"]):
            break
        await asyncio.sleep(0.05)

    kinds = [s["kind"] for s in body["items"]]
    assert "failed_document" in kinds


async def test_phrasing_preserves_the_number_of_nudges(client, owner, fake_llm):
    """A model that merges or drops nudges would silently lose one, and a lost
    deadline is worse than an unpolished sentence."""
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)

    for index in range(3):
        task = await make_task(
            client, owner, owner["workspace_id"], project["id"], f"Task {index}", user_id
        )
        await client.patch(
            f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
            json={"due_date": date.today().isoformat()},
            headers=owner["headers"],
        )

    # The model returns a single line for three nudges — the rewrite must be
    # rejected wholesale rather than applied.
    fake_llm.responses = ["Just one line for everything"]
    body = await suggestions(client, owner)

    assert len(body["items"]) == 3
    assert body["model_used"] is None
    assert all("Task" in s["title"] for s in body["items"])


async def test_good_phrasing_is_applied_and_attributed(client, owner, fake_llm):
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)
    task = await make_task(client, owner, owner["workspace_id"], project["id"], "Original", user_id)
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"due_date": date.today().isoformat()},
        headers=owner["headers"],
    )

    fake_llm.responses = ["Original is due today"]
    body = await suggestions(client, owner)

    assert body["items"][0]["title"] == "Original is due today"
    # Attributed, the same way a chat message names the model that answered.
    assert body["model_used"]


async def test_suggestions_have_stable_ids_across_regeneration(client, owner, fake_llm):
    """Nothing is persisted, so a client-side dismissal only sticks if the id
    survives regeneration."""
    fake_llm.responses = ["", ""]
    project = await make_project(client, owner, owner["workspace_id"], "P")
    user_id = await my_id(client, owner)
    task = await make_task(client, owner, owner["workspace_id"], project["id"], "Repeat", user_id)
    await client.patch(
        f"/workspaces/{owner['workspace_id']}/tasks/{task['id']}",
        json={"due_date": date.today().isoformat()},
        headers=owner["headers"],
    )

    first = await suggestions(client, owner)
    second = await suggestions(client, owner)
    assert [s["id"] for s in first["items"]] == [s["id"] for s in second["items"]]


async def test_suggestions_do_not_cross_the_tenant_boundary(client, owner):
    outsider = await register_account(client, email="rival@other.com", org="Rival")
    response = await client.get(
        f"/workspaces/{owner['workspace_id']}/suggestions", headers=outsider["headers"]
    )
    assert response.status_code == 404


async def test_suggestions_require_authentication(client, owner):
    response = await client.get(f"/workspaces/{owner['workspace_id']}/suggestions")
    assert response.status_code == 401
