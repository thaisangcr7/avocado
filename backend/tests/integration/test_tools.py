"""The tool registry: defaults, activation, cost, and placeholders."""

from __future__ import annotations

import pytest

from tests.conftest import register_account

pytestmark = pytest.mark.anyio


async def conversation(client, account) -> str:
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={"title": "tools"},
        headers=account["headers"],
    )
    return response.json()["id"]


def path(account, conversation_id: str) -> str:
    return f"/workspaces/{account['workspace_id']}/conversations/{conversation_id}/tools"


async def test_the_catalogue_lists_every_tool(client, account):
    listed = await client.get(
        path(account, await conversation(client, account)), headers=account["headers"]
    )
    assert listed.status_code == 200

    body = listed.json()
    assert len(body["tools"]) > 5
    assert {"analytics", "engineering", "knowledge", "admin", "data"} >= {
        t["category"] for t in body["tools"]
    }


async def test_a_fresh_conversation_starts_on_the_defaults(client, account):
    """No selection means the defaults are in force, not that everything is off."""
    body = (
        await client.get(
            path(account, await conversation(client, account)), headers=account["headers"]
        )
    ).json()

    enabled = [t["slug"] for t in body["tools"] if t["enabled"]]
    assert enabled, "a new conversation should have its default tools on"
    assert body["enabled_count"] == len(enabled)


async def test_the_cost_of_the_enabled_set_is_reported(client, account):
    """Every enabled tool spends context whether or not it is called, so the
    total has to be visible rather than discovered as worse answers."""
    conversation_id = await conversation(client, account)
    body = (await client.get(path(account, conversation_id), headers=account["headers"])).json()

    expected = sum(t["context_cost_tokens"] for t in body["tools"] if t["enabled"])
    assert body["context_cost_tokens"] == expected
    assert body["context_cost_tokens"] > 0


async def test_turning_everything_off_costs_nothing(client, account):
    conversation_id = await conversation(client, account)
    updated = await client.put(
        path(account, conversation_id), json={"slugs": []}, headers=account["headers"]
    )
    assert updated.status_code == 200
    assert updated.json()["enabled_count"] == 0
    assert updated.json()["context_cost_tokens"] == 0


async def test_a_selection_survives_a_reread(client, account):
    conversation_id = await conversation(client, account)
    await client.put(
        path(account, conversation_id),
        json={"slugs": ["data-explorer"]},
        headers=account["headers"],
    )

    body = (await client.get(path(account, conversation_id), headers=account["headers"])).json()
    assert [t["slug"] for t in body["tools"] if t["enabled"]] == ["data-explorer"]


async def test_a_placeholder_cannot_be_switched_on(client, account):
    """A tool that is declared but not wired to anything would report success it
    never had. Refusing is better than a tool that silently does nothing."""
    conversation_id = await conversation(client, account)
    body = (await client.get(path(account, conversation_id), headers=account["headers"])).json()
    placeholder = next(t["slug"] for t in body["tools"] if not t["connected"])

    response = await client.put(
        path(account, conversation_id), json={"slugs": [placeholder]}, headers=account["headers"]
    )
    assert response.status_code == 422
    assert "not connected" in response.json()["detail"]


async def test_placeholders_are_shown_rather_than_hidden(client, account):
    """They are the shape of what is coming; hiding them would make the
    registry look emptier than the roadmap is."""
    body = (
        await client.get(
            path(account, await conversation(client, account)), headers=account["headers"]
        )
    ).json()
    assert any(not t["connected"] for t in body["tools"])
    assert all(not t["enabled"] for t in body["tools"] if not t["connected"])


async def test_an_unknown_tool_is_refused(client, account):
    conversation_id = await conversation(client, account)
    response = await client.put(
        path(account, conversation_id), json={"slugs": ["nope"]}, headers=account["headers"]
    )
    assert response.status_code == 404


async def test_tools_do_not_cross_tenants(client):
    alice = await register_account(client, email="alice-tools@example.com", org="Alice Co")
    bob = await register_account(client, email="bob-tools@example.com", org="Bob Co")
    conversation_id = await conversation(client, alice)

    # Bob cannot set tools on Alice's conversation through his own workspace.
    response = await client.put(
        path(bob, conversation_id), json={"slugs": ["data-explorer"]}, headers=bob["headers"]
    )
    assert response.status_code == 404


async def test_a_tool_the_answering_model_cannot_host_reads_as_off(client, account, app):
    """Web search runs on the vendor's side. Pinned to a model whose vendor
    does not host it, the switch would be on and nothing would happen — so it
    reports off instead. A control that lies is worse than one that is absent.
    """
    from app.clients.llm.router import ProviderRegistry
    from tests.fakes import FakeLLMProvider

    class NoServerTools(FakeLLMProvider):
        server_tools = frozenset()

    registry = ProviderRegistry(app.state.settings)
    registry.register(NoServerTools(), make_default=True)
    original = app.state.registry
    app.state.registry = registry
    try:
        conversation_id = await conversation(client, account)
        await client.put(
            path(account, conversation_id),
            json={"slugs": ["web-search"]},
            headers=account["headers"],
        )
        body = (await client.get(path(account, conversation_id), headers=account["headers"])).json()
        web = next(t for t in body["tools"] if t["slug"] == "web-search")

        assert web["enabled"] is False, "it cannot run, so it must not read as on"
        # Still connected and still listed: it is real, just not here.
        assert web["connected"] is True
        assert web["runs_on"] == ["anthropic"]
    finally:
        app.state.registry = original


async def test_a_configured_server_becomes_a_tool_that_can_be_switched_on(client, account, app):
    """The promise the registry was built on: connecting an integration is a
    config row. No migration, no code change, no deployment of this codebase.
    """
    from app.clients.tools.registry import McpServers
    from app.core.config import McpServerConfig

    original = app.state.mcp_servers
    app.state.mcp_servers = McpServers(
        [
            McpServerConfig(
                slug="wiki",
                name="Confluence",
                description="Our knowledge base.",
                url="https://wiki.example.com/mcp",
                context_cost_tokens=390,
            )
        ]
    )
    try:
        conversation_id = await conversation(client, account)
        listed = (
            await client.get(path(account, conversation_id), headers=account["headers"])
        ).json()
        wiki = next(t for t in listed["tools"] if t["slug"] == "wiki")

        # The placeholder card is now live rather than a second card appearing.
        assert wiki["kind"] == "mcp"
        assert wiki["connected"] is True
        assert wiki["name"] == "Confluence"
        assert len([t for t in listed["tools"] if t["slug"] == "wiki"]) == 1
        # Connected is not the same as on: an operator wiring up a server must
        # not silently start sending every conversation's questions to it.
        assert wiki["enabled"] is False

        response = await client.put(
            path(account, conversation_id),
            json={"slugs": ["wiki"]},
            headers=account["headers"],
        )
        assert response.status_code == 200, "a connected server must be switchable on"

        after = next(t for t in response.json()["tools"] if t["slug"] == "wiki")
        assert after["enabled"] is True
        assert response.json()["context_cost_tokens"] >= 390
    finally:
        app.state.mcp_servers = original


async def test_an_mcp_tool_reads_as_off_where_the_model_runs_no_tool_loop(client, account, app):
    """The same honesty as web search, for a different capability: a vendor
    with no tool loop would leave the switch on and the tool never called."""
    from app.clients.llm.router import ProviderRegistry
    from app.clients.tools.registry import McpServers
    from app.core.config import McpServerConfig
    from tests.fakes import FakeLLMProvider

    class NoToolLoop(FakeLLMProvider):
        supports_client_tools = False

    registry = ProviderRegistry(app.state.settings)
    registry.register(NoToolLoop(), make_default=True)
    original_registry, original_servers = app.state.registry, app.state.mcp_servers
    app.state.registry = registry
    app.state.mcp_servers = McpServers(
        [McpServerConfig(slug="wiki", name="Wiki", url="https://wiki.example.com/mcp")]
    )
    try:
        conversation_id = await conversation(client, account)
        await client.put(
            path(account, conversation_id),
            json={"slugs": ["wiki"]},
            headers=account["headers"],
        )
        body = (await client.get(path(account, conversation_id), headers=account["headers"])).json()
        wiki = next(t for t in body["tools"] if t["slug"] == "wiki")

        assert wiki["enabled"] is False, "it cannot run here, so it must not read as on"
        assert wiki["connected"] is True
    finally:
        app.state.registry = original_registry
        app.state.mcp_servers = original_servers
