"""Conversation history: search, filter, pagination, pin, archive, export."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def thread(client, account, title: str) -> str:
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": title},
        headers=account["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def history_path(account, **params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    base = f"/workspaces/{account['workspace_id']}/conversations/history"
    return f"{base}?{query}" if query else base


async def test_history_is_not_swallowed_by_the_id_route(client, account):
    """`/conversations/history` sits beside `/conversations/{id}`. Declared in
    the wrong order, "history" is parsed as a UUID and this 422s."""
    response = await client.get(history_path(account), headers=account["headers"])

    assert response.status_code == 200, response.text
    assert "conversations" in response.json()


async def test_each_row_carries_its_message_count(client, account, fake_llm):
    conversation_id = await thread(client, account, "Counted")
    fake_llm.responses = ["An answer."]
    await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "A question"},
        headers=account["headers"],
    )

    body = (await client.get(history_path(account), headers=account["headers"])).json()
    row = next(c for c in body["conversations"] if c["id"] == conversation_id)

    # One question and one answer.
    assert row["message_count"] == 2


async def test_search_filters_by_title(client, account):
    await thread(client, account, "Quarterly revenue")
    await thread(client, account, "Hiring plan")

    body = (
        await client.get(history_path(account, search="revenue"), headers=account["headers"])
    ).json()

    assert [c["title"] for c in body["conversations"]] == ["Quarterly revenue"]
    assert body["total"] == 1


async def test_a_pinned_thread_sorts_above_a_newer_one(client, account):
    older = await thread(client, account, "Older")
    await thread(client, account, "Newer")

    await client.put(
        f"/workspaces/{account['workspace_id']}/conversations/{older}/flags",
        json={"pinned": True},
        headers=account["headers"],
    )

    body = (await client.get(history_path(account), headers=account["headers"])).json()
    # A pin is a claim that this one matters more than recency.
    assert body["conversations"][0]["id"] == older


async def test_archiving_takes_a_thread_out_of_the_active_filter(client, account):
    conversation_id = await thread(client, account, "Done with this")

    await client.put(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/flags",
        json={"archived": True},
        headers=account["headers"],
    )

    active = (
        await client.get(history_path(account, which="active"), headers=account["headers"])
    ).json()
    archived = (
        await client.get(history_path(account, which="archived"), headers=account["headers"])
    ).json()

    assert conversation_id not in [c["id"] for c in active["conversations"]]
    assert [c["id"] for c in archived["conversations"]] == [conversation_id]


async def test_setting_one_flag_does_not_reset_the_other(client, account):
    conversation_id = await thread(client, account, "Both")
    base = f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/flags"
    await client.put(base, json={"pinned": True}, headers=account["headers"])

    response = await client.put(base, json={"archived": True}, headers=account["headers"])

    assert response.json()["pinned"] is True, "archiving must not silently unpin"
    assert response.json()["archived"] is True


async def test_pagination_reports_the_total_not_just_the_page(client, account):
    for index in range(5):
        await thread(client, account, f"Thread {index}")

    body = (
        await client.get(history_path(account, limit=2, offset=0), headers=account["headers"])
    ).json()

    assert len(body["conversations"]) == 2
    # Numbered pagination needs the count of everything, not of this page.
    assert body["total"] >= 5


async def test_a_second_page_returns_different_rows(client, account):
    for index in range(4):
        await thread(client, account, f"Page test {index}")

    first = (
        await client.get(history_path(account, limit=2, offset=0), headers=account["headers"])
    ).json()
    second = (
        await client.get(history_path(account, limit=2, offset=2), headers=account["headers"])
    ).json()

    ids = {c["id"] for c in first["conversations"]}
    assert ids.isdisjoint({c["id"] for c in second["conversations"]})


# --- export ---------------------------------------------------------------


async def test_a_thread_exports_as_markdown(client, account, fake_llm):
    conversation_id = await thread(client, account, "Refund policy")
    fake_llm.responses = ["Thirty days."]
    await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "How long is the refund window?"},
        headers=account["headers"],
    )

    response = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/export",
        headers=account["headers"],
    )

    assert response.status_code == 200
    assert "# Refund policy" in response.text
    assert "How long is the refund window?" in response.text
    assert "Thirty days." in response.text


async def test_an_export_is_an_attachment_that_cannot_be_sniffed(client, account):
    """It is user-authored text handed back to a browser."""
    conversation_id = await thread(client, account, "Anything")

    response = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/export",
        headers=account["headers"],
    )

    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "anything.md" in response.headers["content-disposition"]


# --- the tenant boundary --------------------------------------------------


async def test_history_never_crosses_a_workspace(client, account):
    from tests.conftest import register_account

    outsider = await register_account(client, email="outsider-history@other.example", org="Other")
    conversation_id = await thread(client, account, "Private thread")

    body = (await client.get(history_path(outsider), headers=outsider["headers"])).json()
    assert conversation_id not in [c["id"] for c in body["conversations"]]

    # And neither the flags nor the export are reachable from outside.
    flags = await client.put(
        f"/workspaces/{outsider['workspace_id']}/conversations/{conversation_id}/flags",
        json={"pinned": True},
        headers=outsider["headers"],
    )
    export = await client.get(
        f"/workspaces/{outsider['workspace_id']}/conversations/{conversation_id}/export",
        headers=outsider["headers"],
    )
    assert flags.status_code == 404
    assert export.status_code == 404


# --- message feedback -----------------------------------------------------


async def answered_thread(client, account, fake_llm) -> tuple[str, str]:
    """A thread with one answer in it. Returns (conversation_id, message_id)."""
    conversation_id = await thread(client, account, "Rated")
    fake_llm.responses = ["An answer worth rating."]
    turn = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "A question"},
        headers=account["headers"],
    )
    return conversation_id, turn.json()["assistant_message"]["id"]


def feedback_path(account, conversation_id, message_id) -> str:
    return (
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}"
        f"/messages/{message_id}/feedback"
    )


async def messages_of(client, account, conversation_id) -> list[dict]:
    return (
        await client.get(
            f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
            headers=account["headers"],
        )
    ).json()


async def test_an_answer_can_be_rated_and_the_rating_survives_a_reload(client, account, fake_llm):
    conversation_id, message_id = await answered_thread(client, account, fake_llm)

    rated = await client.put(
        feedback_path(account, conversation_id, message_id),
        json={"rating": "up"},
        headers=account["headers"],
    )

    assert rated.status_code == 200, rated.text
    rows = await messages_of(client, account, conversation_id)
    assert next(m for m in rows if m["id"] == message_id)["feedback"] == "up"


async def test_changing_your_mind_replaces_the_rating(client, account, fake_llm):
    """Not a second row: a count of thumbs has to stay a count of people."""
    conversation_id, message_id = await answered_thread(client, account, fake_llm)
    path = feedback_path(account, conversation_id, message_id)

    await client.put(path, json={"rating": "up"}, headers=account["headers"])
    await client.put(path, json={"rating": "down"}, headers=account["headers"])

    rows = await messages_of(client, account, conversation_id)
    assert next(m for m in rows if m["id"] == message_id)["feedback"] == "down"


async def test_a_rating_can_be_withdrawn(client, account, fake_llm):
    """Withdrawing is different from never having rated, and both read as null."""
    conversation_id, message_id = await answered_thread(client, account, fake_llm)
    path = feedback_path(account, conversation_id, message_id)
    await client.put(path, json={"rating": "up"}, headers=account["headers"])

    await client.put(path, json={"rating": None}, headers=account["headers"])

    rows = await messages_of(client, account, conversation_id)
    assert next(m for m in rows if m["id"] == message_id)["feedback"] is None


async def test_an_unrated_message_reads_as_unrated(client, account, fake_llm):
    conversation_id, message_id = await answered_thread(client, account, fake_llm)

    rows = await messages_of(client, account, conversation_id)

    assert next(m for m in rows if m["id"] == message_id)["feedback"] is None


async def test_feedback_cannot_be_left_across_a_workspace(client, account, fake_llm):
    from tests.conftest import register_account

    conversation_id, message_id = await answered_thread(client, account, fake_llm)
    outsider = await register_account(client, email="rater@other.example", org="Other")

    response = await client.put(
        feedback_path(outsider, conversation_id, message_id),
        json={"rating": "down"},
        headers=outsider["headers"],
    )

    assert response.status_code == 404
