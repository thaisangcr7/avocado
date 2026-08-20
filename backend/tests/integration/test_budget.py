"""Monthly spend ceilings, and what crossing one does."""

from __future__ import annotations

import io
import uuid

import pytest

from app.models.enums import Role
from tests.conftest import register_account
from tests.integration.test_documents import wait_for_ready
from tests.integration.test_rbac import invite_and_accept

pytestmark = pytest.mark.anyio


@pytest.fixture
async def stocked(client, account):
    """An account whose workspace has a document, so a question reaches a model.

    Without one, retrieval finds nothing and the answer is produced without
    calling a provider at all -- which is correct, and also means no budget is
    ever consulted.
    """
    created = await client.post(
        f"/workspaces/{account['workspace_id']}/documents",
        files={
            "file": (
                "handbook.txt",
                io.BytesIO(b"Expenses over 500 dollars need the finance lead's approval." * 20),
                "text/plain",
            )
        },
        headers=account["headers"],
    )
    assert created.status_code == 201, created.text
    await wait_for_ready(client, created.json()["document"]["id"], account["headers"])
    return account


async def set_budget(client, account, amount):
    return await client.patch(
        "/organizations/current",
        json={"monthly_budget_usd": amount},
        headers=account["headers"],
    )


async def ask(client, account, text="What does the handbook say?"):
    conversation = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": "budget"},
        headers=account["headers"],
    )
    return await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/"
        f"{conversation.json()['id']}/messages",
        json={"content": text},
        headers=account["headers"],
    )


async def test_an_organization_starts_with_no_ceiling(client, account):
    """A budget nobody set must never be the reason a request fails."""
    response = await client.get("/organizations/current", headers=account["headers"])
    assert response.status_code == 200
    assert response.json()["monthly_budget_usd"] is None

    usage = await client.get("/organizations/current/usage", headers=account["headers"])
    assert usage.status_code == 200
    assert usage.json()["budget_state"] == "ok"
    assert usage.json()["budget_used_fraction"] is None


async def test_a_budget_can_be_set_and_cleared(client, account):
    assert (await set_budget(client, account, 25.0)).json()["monthly_budget_usd"] == 25.0
    # Explicit null clears it; that is a different intent from omitting it.
    assert (await set_budget(client, account, None)).json()["monthly_budget_usd"] is None


async def test_setting_a_budget_leaves_the_name_alone(client, account):
    """Both fields are optional, so one must be changeable without the other."""
    before = (await client.get("/organizations/current", headers=account["headers"])).json()
    after = (await set_budget(client, account, 10.0)).json()
    assert after["name"] == before["name"]


async def test_a_negative_budget_is_rejected(client, account):
    response = await set_budget(client, account, -1.0)
    assert response.status_code == 422


async def test_a_question_that_never_reaches_a_model_ignores_the_budget(client, account):
    """An empty workspace answers without a provider call, so nothing bills.

    The guard sits at model resolution rather than at the endpoint, so a request
    that costs nothing is not refused for lack of budget.
    """
    await set_budget(client, account, 0.0000001)
    assert (await ask(client, account)).status_code == 201


async def test_an_exhausted_budget_stops_generation(client, stocked):
    """Spend first, then set a ceiling below it: the next call must not bill.

    402 rather than 429: waiting will not clear it inside the month, someone
    has to raise the limit.
    """
    account = stocked
    question = "What needs the finance lead's approval?"
    assert (await ask(client, account, question)).status_code == 201

    spent = (await client.get("/organizations/current/usage", headers=account["headers"])).json()[
        "cost_usd"
    ]
    assert spent > 0, "the first call should have recorded a cost to exceed"

    await set_budget(client, account, spent / 2)
    response = await ask(client, account, question)
    assert response.status_code == 402, response.text
    assert "monthly spend limit" in response.json()["detail"]


async def test_generation_resumes_when_the_ceiling_is_raised(client, stocked):
    account = stocked
    question = "What needs the finance lead's approval?"
    assert (await ask(client, account, question)).status_code == 201

    spent = (await client.get("/organizations/current/usage", headers=account["headers"])).json()[
        "cost_usd"
    ]
    await set_budget(client, account, spent / 2)
    assert (await ask(client, account, question)).status_code == 402

    await set_budget(client, account, 1000.0)
    assert (await ask(client, account, question)).status_code == 201


async def test_usage_reports_spend_after_a_call(client, stocked):
    account = stocked
    await ask(client, account, "What needs the finance lead's approval?")
    usage = (await client.get("/organizations/current/usage", headers=account["headers"])).json()
    assert usage["calls"] >= 1
    assert usage["by_model"], "spend should be attributed to a model"


async def test_only_an_org_admin_can_read_usage(client):
    """Per-model cost is a commercial detail, not something every member sees."""
    founder = await register_account(client, email="boss@acme.com", org="Acme")
    team_id = (await client.get("/teams", headers=founder["headers"])).json()[0]["id"]
    member = await invite_and_accept(
        client, founder, team_id, f"member-{uuid.uuid4().hex[:6]}@acme.com", Role.MEMBER
    )

    assert (
        await client.get("/organizations/current/usage", headers=founder["headers"])
    ).status_code == 200
    assert (
        await client.get("/organizations/current/usage", headers=member["headers"])
    ).status_code == 403
