"""Task visibility.

Architecture §15 names this alongside the tenant-isolation test, and §11 is
explicit about why it is separate: task visibility is *not* document
visibility. Everyone in a workspace can typically read every document, but a
task assigned to one person is not workspace-public just because it lives in a
shared workspace.

A task is visible to its assignee, to members of its project, to team admins —
and to the whole workspace only when the project has opted in.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import Role
from tests.conftest import register_account
from tests.integration.test_rbac import invite_and_accept

pytestmark = pytest.mark.anyio


@pytest.fixture
async def company(client):
    """One org, one workspace, four people at different standings."""
    founder = await register_account(client, email="founder@acme.com", org="Acme")
    teams = await client.get("/teams", headers=founder["headers"])
    team_id = teams.json()[0]["id"]

    alice = await invite_and_accept(client, founder, team_id, "alice@acme.com", Role.MEMBER)
    bob = await invite_and_accept(client, founder, team_id, "bob@acme.com", Role.MEMBER)
    carol = await invite_and_accept(client, founder, team_id, "carol@acme.com", Role.MEMBER)

    async def user_id(account):
        return (await client.get("/auth/me", headers=account["headers"])).json()["id"]

    return {
        "workspace_id": founder["workspace_id"],
        "team_id": team_id,
        "admin": founder,
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "alice_id": await user_id(alice),
        "bob_id": await user_id(bob),
        "carol_id": await user_id(carol),
    }


async def make_project(client, account, workspace_id, name, visibility="restricted", members=()):
    response = await client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": name, "visibility": visibility, "member_ids": list(members)},
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_task(client, account, workspace_id, project_id, title, assignee_id=None):
    response = await client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/tasks",
        json={"title": title, **({"assignee_id": assignee_id} if assignee_id else {})},
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


async def visible_task_titles(client, account, workspace_id):
    response = await client.get(f"/workspaces/{workspace_id}/tasks", headers=account["headers"])
    assert response.status_code == 200, response.text
    return {t["title"] for t in response.json()}


# --- the core rule ---------------------------------------------------------


async def test_a_task_is_not_workspace_public_by_default(client, company):
    """The whole point of §11: a shared workspace does not make a task shared."""
    project = await make_project(
        client, company["alice"], company["workspace_id"], "Alice's project"
    )
    await make_task(
        client, company["alice"], company["workspace_id"], project["id"], "Private work"
    )

    assert "Private work" in await visible_task_titles(
        client, company["alice"], company["workspace_id"]
    )
    # Carol is in the same workspace and can read every document in it.
    assert "Private work" not in await visible_task_titles(
        client, company["carol"], company["workspace_id"]
    )


async def test_the_assignee_sees_their_task(client, company):
    """Being assigned is the strongest visibility grant there is."""
    project = await make_project(client, company["alice"], company["workspace_id"], "Delegation")
    await make_task(
        client,
        company["alice"],
        company["workspace_id"],
        project["id"],
        "Bob's job",
        assignee_id=company["bob_id"],
    )

    # Bob is not a member of Alice's project, only the assignee.
    assert "Bob's job" in await visible_task_titles(client, company["bob"], company["workspace_id"])
    assert "Bob's job" not in await visible_task_titles(
        client, company["carol"], company["workspace_id"]
    )


async def test_project_members_see_the_projects_tasks(client, company):
    project = await make_project(
        client,
        company["alice"],
        company["workspace_id"],
        "Shared project",
        members=[company["bob_id"]],
    )
    await make_task(client, company["alice"], company["workspace_id"], project["id"], "Team task")

    assert "Team task" in await visible_task_titles(client, company["bob"], company["workspace_id"])
    assert "Team task" not in await visible_task_titles(
        client, company["carol"], company["workspace_id"]
    )


async def test_a_workspace_visible_project_opens_its_board(client, company):
    """Broader visibility is an opt-in on the project, never the default."""
    project = await make_project(
        client,
        company["alice"],
        company["workspace_id"],
        "Public roadmap",
        visibility="workspace",
    )
    await make_task(client, company["alice"], company["workspace_id"], project["id"], "Open task")

    assert "Open task" in await visible_task_titles(
        client, company["carol"], company["workspace_id"]
    )


async def test_an_admin_sees_every_task_in_the_workspace(client, company):
    project = await make_project(client, company["alice"], company["workspace_id"], "Alice only")
    await make_task(
        client, company["alice"], company["workspace_id"], project["id"], "Admin can see"
    )

    assert "Admin can see" in await visible_task_titles(
        client, company["admin"], company["workspace_id"]
    )


async def test_opening_a_project_reveals_its_existing_tasks(client, company):
    """Visibility follows the project's current setting, not the one it had
    when the task was created."""
    project = await make_project(client, company["alice"], company["workspace_id"], "Will open")
    await make_task(
        client, company["alice"], company["workspace_id"], project["id"], "Later public"
    )
    assert "Later public" not in await visible_task_titles(
        client, company["carol"], company["workspace_id"]
    )

    await client.patch(
        f"/workspaces/{company['workspace_id']}/projects/{project['id']}",
        json={"visibility": "workspace"},
        headers=company["alice"]["headers"],
    )
    assert "Later public" in await visible_task_titles(
        client, company["carol"], company["workspace_id"]
    )


async def test_removing_a_member_withdraws_their_view(client, company):
    project = await make_project(
        client,
        company["alice"],
        company["workspace_id"],
        "Temporary access",
        members=[company["bob_id"]],
    )
    await make_task(client, company["alice"], company["workspace_id"], project["id"], "Was shared")
    assert "Was shared" in await visible_task_titles(
        client, company["bob"], company["workspace_id"]
    )

    removed = await client.delete(
        f"/workspaces/{company['workspace_id']}/projects/{project['id']}/members/{company['bob_id']}",
        headers=company["alice"]["headers"],
    )
    assert removed.status_code == 200
    assert "Was shared" not in await visible_task_titles(
        client, company["bob"], company["workspace_id"]
    )


# --- fetching one task directly -------------------------------------------


async def test_an_invisible_task_reads_as_absent(client, company):
    """404, not 403 — confirming a task exists is itself a disclosure."""
    project = await make_project(client, company["alice"], company["workspace_id"], "Hidden")
    task = await make_task(
        client, company["alice"], company["workspace_id"], project["id"], "Secret"
    )

    response = await client.get(
        f"/workspaces/{company['workspace_id']}/tasks/{task['id']}",
        headers=company["carol"]["headers"],
    )
    assert response.status_code == 404


async def test_an_invisible_task_cannot_be_modified(client, company):
    project = await make_project(client, company["alice"], company["workspace_id"], "Hidden too")
    task = await make_task(
        client, company["alice"], company["workspace_id"], project["id"], "Untouchable"
    )
    path = f"/workspaces/{company['workspace_id']}/tasks/{task['id']}"

    assert (
        await client.patch(path, json={"title": "Hijacked"}, headers=company["carol"]["headers"])
    ).status_code == 404
    assert (await client.delete(path, headers=company["carol"]["headers"])).status_code == 404
    assert (
        await client.get(f"{path}/resume", headers=company["carol"]["headers"])
    ).status_code == 404


async def test_an_invisible_project_reads_as_absent(client, company):
    project = await make_project(client, company["alice"], company["workspace_id"], "Alice's own")
    response = await client.get(
        f"/workspaces/{company['workspace_id']}/projects/{project['id']}",
        headers=company["carol"]["headers"],
    )
    assert response.status_code == 404


async def test_holding_a_task_makes_its_project_reachable(client, company):
    """Otherwise someone could hold a task in a project they cannot open,
    leaving it unreachable from the UI."""
    project = await make_project(client, company["alice"], company["workspace_id"], "Assigned out")
    await make_task(
        client,
        company["alice"],
        company["workspace_id"],
        project["id"],
        "Bob's task",
        assignee_id=company["bob_id"],
    )

    listed = await client.get(
        f"/workspaces/{company['workspace_id']}/projects", headers=company["bob"]["headers"]
    )
    assert project["id"] in [p["id"] for p in listed.json()]


# --- authority is not membership ------------------------------------------


async def test_a_member_cannot_reshape_a_project_they_merely_belong_to(client, company):
    """Membership grants sight, not authority — otherwise anyone added to a
    board could delete it."""
    project = await make_project(
        client,
        company["alice"],
        company["workspace_id"],
        "Alice's board",
        members=[company["bob_id"]],
    )

    assert (
        await client.patch(
            f"/workspaces/{company['workspace_id']}/projects/{project['id']}",
            json={"name": "Bob's board"},
            headers=company["bob"]["headers"],
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/workspaces/{company['workspace_id']}/projects/{project['id']}",
            headers=company["bob"]["headers"],
        )
    ).status_code == 403


async def test_an_admin_can_reshape_any_project(client, company):
    project = await make_project(client, company["alice"], company["workspace_id"], "Alice's")
    response = await client.patch(
        f"/workspaces/{company['workspace_id']}/projects/{project['id']}",
        json={"status": "archived"},
        headers=company["admin"]["headers"],
    )
    assert response.status_code == 200


# --- tenant isolation still holds -----------------------------------------


async def test_tasks_do_not_cross_the_tenant_boundary(client, company):
    outsider = await register_account(client, email="rival@other.com", org="Rival")
    project = await make_project(
        client,
        company["alice"],
        company["workspace_id"],
        "Internal",
        visibility="workspace",
    )
    task = await make_task(
        client, company["alice"], company["workspace_id"], project["id"], "Even if open"
    )

    # Workspace-visible does not mean world-visible.
    assert (
        await client.get(
            f"/workspaces/{company['workspace_id']}/tasks", headers=outsider["headers"]
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/workspaces/{company['workspace_id']}/tasks/{task['id']}",
            headers=outsider["headers"],
        )
    ).status_code == 404


async def test_an_unknown_task_reads_as_absent(client, company):
    response = await client.get(
        f"/workspaces/{company['workspace_id']}/tasks/{uuid.uuid4()}",
        headers=company["admin"]["headers"],
    )
    assert response.status_code == 404
