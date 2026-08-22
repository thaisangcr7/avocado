"""Conversations, grounded answers, and citation handling."""

from __future__ import annotations

import json

import pytest

from app.clients.sandbox.base import SandboxResult
from tests.conftest import quiesce_llm
from tests.integration.test_documents import upload, wait_for_ready

pytestmark = pytest.mark.anyio

POLICY = (
    "Remote work policy. Employees may work from home up to three days per week. "
    "Expense reports must be submitted within thirty days. "
    "The annual training budget is two thousand dollars per person."
)


async def seed_document(client, account, content: bytes = None):
    response = await upload(
        client, account, "policy.txt", content or (POLICY.encode() * 5), "text/plain"
    )
    assert response.status_code == 201
    return await wait_for_ready(client, response.json()["document"]["id"], account["headers"])


async def new_conversation(client, account, title="Test thread"):
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": title},
        headers=account["headers"],
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_conversation_crud(client, account):
    conversation_id = await new_conversation(client, account, "Original title")

    listed = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations", headers=account["headers"]
    )
    assert [c["id"] for c in listed.json()] == [conversation_id]

    renamed = await client.patch(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}",
        json={"title": "Renamed thread"},
        headers=account["headers"],
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed thread"

    deleted = await client.delete(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}",
        headers=account["headers"],
    )
    assert deleted.status_code == 200

    gone = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}",
        headers=account["headers"],
    )
    assert gone.status_code == 404


async def test_a_question_returns_both_halves_of_the_turn(client, account):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "How many days can employees work from home?"},
        headers=account["headers"],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["role"] == "assistant"
    # The model that answered is always recorded, so Auto is never opaque.
    assert body["assistant_message"]["model_used"]


async def test_a_cited_answer_carries_its_sources(client, account, fake_llm):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    fake_llm.responses = ["Employees may work from home three days per week. [1]"]
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work from home policy days per week"},
        headers=account["headers"],
    )

    citations = response.json()["assistant_message"]["citations"]
    assert len(citations) == 1
    citation = citations[0]
    assert citation["document_name"] == "policy.txt"
    assert citation["snippet"]
    assert 0.0 <= citation["score"] <= 1.0


async def test_uncited_sources_are_not_attached(client, account, fake_llm):
    """Citations are evidence the answer used a source, not a dump of hits."""
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    fake_llm.responses = ["I am answering without pointing at anything."]
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work policy"},
        headers=account["headers"],
    )
    assert response.json()["assistant_message"]["citations"] == []


async def test_out_of_range_citation_numbers_are_ignored(client, account, fake_llm):
    """A model can emit [9] when far fewer sources were supplied."""
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    fake_llm.responses = ["Claiming a source that does not exist. [99]"]
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work policy"},
        headers=account["headers"],
    )
    assert response.json()["assistant_message"]["citations"] == []


async def test_a_greeting_is_answered_rather_than_searched_for(client, account, fake_llm):
    """ "Hello" retrieves nothing, and telling someone their greeting did not
    match any document is what makes an assistant feel like a search box."""
    conversation_id = await new_conversation(client, account)
    fake_llm.responses = ["Hi. Upload a document and I can answer questions about it."]

    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "hello"},
        headers=account["headers"],
    )
    assert response.status_code == 201
    answer = response.json()["assistant_message"]
    assert "could not find" not in answer["content"].lower()
    # Nothing was retrieved, so nothing may be cited whatever the reply says.
    assert answer["citations"] == []


async def test_an_unanswerable_question_still_says_so(client, account, fake_llm):
    """The friendlier greeting must not cost the honesty guarantee: a question
    the workspace cannot answer is still refused, not answered from general
    knowledge."""
    conversation_id = await new_conversation(client, account)
    fake_llm.responses = ["Nothing in this workspace covers a remote work policy."]

    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "What is the remote work policy?"},
        headers=account["headers"],
    )
    answer = response.json()["assistant_message"]
    assert answer["citations"] == []

    # The prompt that produced it is the guarantee, so assert the instruction
    # is actually being sent rather than trusting the fake's scripted reply.
    system = fake_llm.calls[-1]["system"]
    assert "Never answer" in system
    assert "general knowledge" in system


async def test_an_empty_workspace_answers_even_with_no_provider_configured(client, account, app):
    """A fresh deployment has no LLM key yet, which is exactly when an honest
    "nothing here" is most useful. Resolving a model first would 502 instead."""
    from app.clients.llm.router import ModelRouter, ProviderRegistry

    # A registry with nothing registered and no credentials configured.
    empty = ProviderRegistry(app.state.settings)
    app.state.registry = empty
    app.state.model_router = ModelRouter(empty)

    conversation_id = await new_conversation(client, account)
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "anything at all"},
        headers=account["headers"],
    )

    assert response.status_code == 201
    answer = response.json()["assistant_message"]
    assert "could not find" in answer["content"].lower()
    # No model was involved, and the response says so rather than naming one.
    assert answer["model_used"] is None


async def test_the_first_exchange_names_the_thread(client, account, fake_llm):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    fake_llm.responses = ["An answer. [1]", "Remote Work Policy"]
    await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work policy"},
        headers=account["headers"],
    )

    conversation = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}",
        headers=account["headers"],
    )
    assert conversation.json()["title"] != "New conversation"


async def test_history_accumulates_in_order(client, account):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    for question in ("first question", "second question"):
        await client.post(
            f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
            json={"content": question},
            headers=account["headers"],
        )

    messages = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        headers=account["headers"],
    )
    roles = [m["role"] for m in messages.json()]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert messages.json()[0]["content"] == "first question"


async def test_retrieval_can_be_restricted_to_chosen_documents(client, account):
    await seed_document(client, account)
    other = await upload(
        client,
        account,
        "unrelated.txt",
        b"Cafeteria menu and parking information. " * 20,
        "text/plain",
    )
    other_doc = await wait_for_ready(client, other.json()["document"]["id"], account["headers"])

    conversation_id = await new_conversation(client, account)
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work policy", "document_ids": [other_doc["id"]]},
        headers=account["headers"],
    )

    # Any citation must come from the one document that was allowed.
    for citation in response.json()["assistant_message"]["citations"]:
        assert citation["document_id"] == other_doc["id"]


async def test_streaming_emits_citations_then_tokens_then_done(client, account, fake_llm):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)
    fake_llm.responses = ["Streaming answer here. [1]"]

    async with client.stream(
        "POST",
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages/stream",
        json={"content": "remote work policy"},
        headers=account["headers"],
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events, payloads = [], []
        current = None
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current = line[7:]
                events.append(current)
            elif line.startswith("data: "):
                payloads.append((current, json.loads(line[6:])))

    assert events[0] == "citations"
    assert events[-1] == "done"
    assert "token" in events

    text = "".join(data["text"] for name, data in payloads if name == "token")
    assert "Streaming answer" in text

    done = next(data for name, data in payloads if name == "done")
    assert done["model"]
    assert len(done["citations"]) == 1


async def test_analytical_chat_question_runs_full_spreadsheet_analysis(client, account):
    uploaded = await upload(
        client,
        account,
        "revenue_by_region.csv",
        b"month,region,revenue\n2025-01,North,100\n2025-01,South,80\n",
        "text/csv",
    )
    document = await wait_for_ready(client, uploaded.json()["document"]["id"], account["headers"])
    conversation_id = await new_conversation(client, account)

    events: list[tuple[str | None, dict]] = []
    current = None
    async with client.stream(
        "POST",
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages/stream",
        json={
            "content": "Create a dashboard showing the revenue trend by region.",
        },
        headers=account["headers"],
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current = line[7:]
            elif line.startswith("data: "):
                events.append((current, json.loads(line[6:])))

    names = [name for name, _ in events]
    assert names == ["analysis_started", "analysis_completed", "done"]
    completed = next(data for name, data in events if name == "analysis_completed")
    assert completed["document_id"] == document["id"]
    assert completed["run"]["status"] == "succeeded"
    assert completed["run"]["result_data"]["tables"][0]["total_rows"] == 2

    messages = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        headers=account["headers"],
    )
    assert [message["role"] for message in messages.json()] == ["user", "assistant"]


async def test_a_streamed_turn_is_persisted(client, account, fake_llm):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)
    fake_llm.responses = ["Persisted streamed answer. [1]"]

    async with client.stream(
        "POST",
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages/stream",
        json={"content": "remote work policy"},
        headers=account["headers"],
    ) as response:
        async for _ in response.aiter_lines():
            pass

    messages = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        headers=account["headers"],
    )
    roles = [m["role"] for m in messages.json()]
    assert roles == ["user", "assistant"]
    assert "Persisted streamed answer" in messages.json()[1]["content"]


async def test_an_empty_message_is_rejected(client, account):
    conversation_id = await new_conversation(client, account)
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": ""},
        headers=account["headers"],
    )
    assert response.status_code == 422


async def test_a_failed_generation_is_recorded_in_the_thread(client, account, app):
    """The user's turn genuinely happened, so the question stays. Without a
    record beside it, a reload shows a question with no reply and no
    explanation once the transient error notice is gone."""
    from app.clients.llm.router import ModelRouter, ProviderRegistry

    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    # No provider configured, as on a deployment with no LLM key.
    empty = ProviderRegistry(app.state.settings)
    app.state.registry = empty
    app.state.model_router = ModelRouter(empty)

    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work policy"},
        headers=account["headers"],
    )
    # The status code still reflects reality: the answer did not happen.
    assert response.status_code == 502

    messages = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        headers=account["headers"],
    )
    roles = [(m["role"], m["failed"]) for m in messages.json()]
    assert roles == [("user", False), ("assistant", True)]

    failure = messages.json()[1]
    assert "provider" in failure["content"].lower()
    assert failure["model_used"] is None


async def test_a_successful_turn_is_not_marked_failed(client, account):
    await seed_document(client, account)
    conversation_id = await new_conversation(client, account)

    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "remote work policy"},
        headers=account["headers"],
    )
    assert response.status_code == 201
    assert response.json()["assistant_message"]["failed"] is False


async def test_a_workspace_report_is_streamed_and_persisted(
    client, account, fake_llm, fake_sandbox
):
    """An executive-summary ask over several spreadsheets produces a computed,
    persisted report artifact rather than a single-file analysis."""
    for name in ("revenue_by_region.csv", "support_backlog.csv"):
        uploaded = await upload(
            client,
            account,
            name,
            b"month,region,revenue\n2025-01,North,100\n2025-02,North,120\n",
            "text/csv",
        )
        await wait_for_ready(client, uploaded.json()["document"]["id"], account["headers"])
    await quiesce_llm(fake_llm)

    profile = {
        "datasets": [
            {
                "name": "revenue_by_region.csv",
                "kpis": [{"key": "rev|total", "label": "revenue total", "value": 25400000}],
                "series": [
                    {
                        "key": "rev__by_region",
                        "title": "revenue by region",
                        "columns": ["region", "revenue"],
                        "rows": [["North", 7120000], ["South", 7030000]],
                    }
                ],
            }
        ]
    }
    plan = {
        "title": "Northwind HQ Executive Briefing",
        "thesis": "Revenue is ahead of plan.",
        "heading_status": "on_course",
        "kpis": [
            {
                "source_key": "rev|total",
                "label": "Revenue",
                "context": "trailing",
                "tone": "positive",
                "format": "compact_currency",
            }
        ],
        "sections": [
            {
                "title": "Revenue & Growth",
                "status": "on_course",
                "narrative": "North leads.",
                "charts": [
                    {
                        "title": "Revenue by region",
                        "description": None,
                        "mark": "bar",
                        "series_key": "rev__by_region",
                        "x": {"field": "region", "type": "nominal", "title": None, "format": None},
                        "y": {
                            "field": "revenue",
                            "type": "quantitative",
                            "title": None,
                            "format": None,
                        },
                        "color": None,
                    }
                ],
            }
        ],
        "limits": [],
    }
    fake_sandbox.results = [
        SandboxResult(success=True, scalars={"result": profile}, execution_ms=7)
    ]
    fake_llm.responses = [json.dumps(plan)]

    conversation_id = await new_conversation(client, account)
    events: list[tuple[str | None, dict]] = []
    current = None
    async with client.stream(
        "POST",
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages/stream",
        json={"content": "Give me an executive summary of the whole workspace."},
        headers=account["headers"],
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current = line[7:]
            elif line.startswith("data: "):
                events.append((current, json.loads(line[6:])))

    names = [name for name, _ in events]
    assert names == ["report_started", "report_completed", "done"]
    report = next(data for name, data in events if name == "report_completed")["report"]
    assert report["title"] == "Northwind HQ Executive Briefing"
    # The KPI value is the computed scalar, formatted — not authored by the model.
    assert report["kpis"][0]["value"] == "$25.4M"
    assert report["sections"][0]["charts"][0]["series_key"] == "rev__by_region"

    messages = await client.get(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        headers=account["headers"],
    )
    assistant = messages.json()[1]
    assert assistant["report_artifact"]["title"] == "Northwind HQ Executive Briefing"


async def test_web_search_is_offered_only_when_switched_on(client, account, fake_llm):
    """The tool picker and the answer path have to agree, or a switch a user
    looked at does nothing."""
    conversation_id = await new_conversation(client, account)
    path = f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/tools"

    fake_llm.responses = ["Nothing here covers that."]
    await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "What happened in the news today?"},
        headers=account["headers"],
    )
    assert fake_llm.calls[-1]["server_tools"] == [], "off by default, so nothing is offered"

    await client.put(path, json={"slugs": ["web-search"]}, headers=account["headers"])
    fake_llm.responses = ["From the web: something happened."]
    await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "What happened in the news today?"},
        headers=account["headers"],
    )
    assert fake_llm.calls[-1]["server_tools"] == ["web_search"]


async def test_web_search_is_told_to_separate_the_web_from_the_documents(client, account, fake_llm):
    """A reader has to be able to tell which a claim rests on; the only thing
    carrying that distinction is the instruction the model was given."""
    conversation_id = await new_conversation(client, account)
    await client.put(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/tools",
        json={"slugs": ["web-search"]},
        headers=account["headers"],
    )

    fake_llm.responses = ["From the web."]
    await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/messages",
        json={"content": "What is the latest on this?"},
        headers=account["headers"],
    )
    system = fake_llm.calls[-1]["system"]
    assert "not from their documents" in system
    assert "rather than answering from memory" in system
