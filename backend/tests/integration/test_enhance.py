"""The prompt wand.

The rule that matters is the one it would be easy to get wrong: it must not
answer. A "make this better" prompt whose model helpfully replies instead of
sharpening leaves the user about to send an answer as their question.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


def path(account) -> str:
    return f"/workspaces/{account['workspace_id']}/enhance"


async def test_it_returns_a_sharpened_draft(client, account, fake_llm):
    fake_llm.responses = ["What is our remote work policy for engineering staff?"]

    response = await client.post(
        path(account), json={"draft": "remote work"}, headers=account["headers"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draft"] == "What is our remote work policy for engineering staff?"
    assert body["original"] == "remote work"
    assert body["changed"] is True


async def test_it_is_told_not_to_answer(client, account, fake_llm):
    fake_llm.responses = ["Sharpened."]

    await client.post(path(account), json={"draft": "refunds"}, headers=account["headers"])

    assert "Never answer it" in fake_llm.calls[-1]["system"]


async def test_a_model_that_answered_instead_is_ignored(client, account, fake_llm):
    """Better the original draft than silently replacing someone's question
    with an answer to it."""
    fake_llm.responses = ["Our refund window is thirty days. " * 40]

    response = await client.post(
        path(account), json={"draft": "refunds"}, headers=account["headers"]
    )

    body = response.json()
    assert body["draft"] == "refunds"
    assert body["changed"] is False


async def test_it_uses_the_cheap_tier(client, account, fake_llm):
    """It runs while someone waits with their hand on the keyboard."""
    fake_llm.responses = ["Sharpened."]

    await client.post(path(account), json={"draft": "refunds"}, headers=account["headers"])

    assert fake_llm.calls[-1]["max_tokens"] <= 300


async def test_an_empty_draft_is_refused(client, account):
    response = await client.post(path(account), json={"draft": "   "}, headers=account["headers"])

    assert response.status_code == 422


async def test_a_draft_that_did_not_need_changing_says_so(client, account, fake_llm):
    fake_llm.responses = ["What is our refund policy?"]

    response = await client.post(
        path(account),
        json={"draft": "What is our refund policy?"},
        headers=account["headers"],
    )

    assert response.json()["changed"] is False


async def test_enhance_requires_access_to_the_workspace(client, account):
    from tests.conftest import register_account

    outsider = await register_account(client, email="wand@other.example", org="Other")

    response = await client.post(
        f"/workspaces/{account['workspace_id']}/enhance",
        json={"draft": "anything"},
        headers=outsider["headers"],
    )

    assert response.status_code == 404
