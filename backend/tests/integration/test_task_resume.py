"""Picking a task back up.

§11: returning to a task after two days on something else should start with
"here is where we left off", not a blank chat.
"""

from __future__ import annotations

import pytest

from tests.conftest import register_account
from tests.integration.test_task_visibility import make_project, make_task

pytestmark = pytest.mark.anyio


@pytest.fixture
async def workspace(client):
    account = await register_account(client, email="owner@acme.com", org="Acme")
    return account


async def test_resuming_a_fresh_task_creates_its_thread(client, workspace):
    """A task nobody has discussed still resumes into somewhere to talk."""
    project = await make_project(client, workspace, workspace["workspace_id"], "P")
    task = await make_task(
        client, workspace, workspace["workspace_id"], project["id"], "Draft the spec"
    )

    response = await client.get(
        f"/workspaces/{workspace['workspace_id']}/tasks/{task['id']}/resume",
        headers=workspace["headers"],
    )
    assert response.status_code == 200
    body = response.json()

    assert body["conversation_id"]
    assert body["message_count"] == 0
    assert body["last_activity_at"] is None
    # Nothing was synthesised, and the response says so rather than dressing
    # up boilerplate as a summary.
    assert body["synthesized"] is False
    assert "Draft the spec" in body["summary"]


async def test_the_task_thread_is_stable_across_resumes(client, workspace):
    project = await make_project(client, workspace, workspace["workspace_id"], "P")
    task = await make_task(client, workspace, workspace["workspace_id"], project["id"], "T")
    path = f"/workspaces/{workspace['workspace_id']}/tasks/{task['id']}/resume"

    first = (await client.get(path, headers=workspace["headers"])).json()
    second = (await client.get(path, headers=workspace["headers"])).json()

    # Resuming twice must not strand the earlier conversation.
    assert first["conversation_id"] == second["conversation_id"]


async def test_a_discussed_task_is_summarised(client, workspace, fake_llm):
    from tests.integration.test_documents import upload, wait_for_ready

    uploaded = await upload(
        client, workspace, "notes.txt", b"The migration plan is due in March. " * 30, "text/plain"
    )
    await wait_for_ready(client, uploaded.json()["document"]["id"], workspace["headers"])

    project = await make_project(client, workspace, workspace["workspace_id"], "P")
    task = await make_task(client, workspace, workspace["workspace_id"], project["id"], "Migrate")
    path = f"/workspaces/{workspace['workspace_id']}/tasks/{task['id']}/resume"

    conversation_id = (await client.get(path, headers=workspace["headers"])).json()[
        "conversation_id"
    ]

    fake_llm.responses = ["We decided to migrate in March. [1]"]
    await client.post(
        f"/workspaces/{workspace['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "when is the migration plan due"},
        headers=workspace["headers"],
    )

    fake_llm.responses = ["You were working out the migration timing; March was agreed."]
    resumed = (await client.get(path, headers=workspace["headers"])).json()

    assert resumed["message_count"] >= 2
    assert resumed["last_activity_at"] is not None
    assert resumed["synthesized"] is True
    assert "March" in resumed["summary"]


async def test_a_summary_failure_still_opens_the_task(client, workspace, app):
    """Losing the thread because the summary could not be written would be the
    worse outcome by far."""
    from app.clients.llm.router import ModelRouter, ProviderRegistry
    from tests.integration.test_documents import upload, wait_for_ready

    uploaded = await upload(
        client, workspace, "n.txt", b"content for retrieval " * 30, "text/plain"
    )
    await wait_for_ready(client, uploaded.json()["document"]["id"], workspace["headers"])

    project = await make_project(client, workspace, workspace["workspace_id"], "P")
    task = await make_task(client, workspace, workspace["workspace_id"], project["id"], "T")
    path = f"/workspaces/{workspace['workspace_id']}/tasks/{task['id']}/resume"

    conversation_id = (await client.get(path, headers=workspace["headers"])).json()[
        "conversation_id"
    ]
    await client.post(
        f"/workspaces/{workspace['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "content for retrieval"},
        headers=workspace["headers"],
    )

    # No provider at all, as on a deployment with no LLM key.
    empty = ProviderRegistry(app.state.settings)
    app.state.registry = empty
    app.state.model_router = ModelRouter(empty)

    response = await client.get(path, headers=workspace["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["synthesized"] is False
    assert body["summary"]
    assert body["conversation_id"] == conversation_id


async def test_resuming_reports_a_blocked_task(client, workspace):
    project = await make_project(client, workspace, workspace["workspace_id"], "P")
    task = await make_task(client, workspace, workspace["workspace_id"], project["id"], "Stuck")
    await client.patch(
        f"/workspaces/{workspace['workspace_id']}/tasks/{task['id']}",
        json={"status": "blocked"},
        headers=workspace["headers"],
    )

    body = (
        await client.get(
            f"/workspaces/{workspace['workspace_id']}/tasks/{task['id']}/resume",
            headers=workspace["headers"],
        )
    ).json()
    assert "blocked" in body["summary"].lower()
