"""Naming tools across servers, and finding the way back.

The model is shown one flat list and asks for one name. Two servers may each
offer `search`, so the name has to carry which server owns it — and a name that
does not lead back is a call into nothing.
"""

from __future__ import annotations

import pytest

from app.clients.tools.base import RemoteTool, ToolCallResult, ToolTransport, ToolTransportError
from app.clients.tools.registry import McpServers
from app.core.config import McpServerConfig
from app.services.tool_runner import ToolRunner

pytestmark = pytest.mark.anyio


class FakeTransport(ToolTransport):
    name = "fake"

    def __init__(self, tools: list[RemoteTool], *, down: bool = False) -> None:
        self._tools = tools
        self._down = down
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[RemoteTool]:
        if self._down:
            raise ToolTransportError("'wiki' is unreachable.")
        return self._tools

    async def call(self, name: str, arguments: dict) -> ToolCallResult:
        self.calls.append((name, arguments))
        if self._down:
            raise ToolTransportError("'wiki' is unreachable.")
        return ToolCallResult(text=f"{name} says hello")


def runner_with(transports: dict[str, FakeTransport]) -> ToolRunner:
    configs = [
        McpServerConfig(slug=slug, name=slug, url=f"https://{slug}.example/mcp")
        for slug in transports
    ]
    servers = McpServers(configs)
    for slug, transport in transports.items():
        servers._clients[slug] = transport  # noqa: SLF001 - the seam a fake plugs into
    return ToolRunner(servers)


SEARCH = RemoteTool(name="search", description="Search it.", input_schema={"type": "object"})


async def test_two_servers_offering_the_same_tool_stay_distinguishable():
    runner = runner_with({"wiki": FakeTransport([SEARCH]), "crm": FakeTransport([SEARCH])})

    schemas = await runner.schemas(["wiki", "crm"])

    assert sorted(s.name for s in schemas) == ["crm__search", "wiki__search"]


async def test_a_call_goes_back_to_the_server_that_owns_the_name():
    wiki, crm = FakeTransport([SEARCH]), FakeTransport([SEARCH])
    runner = runner_with({"wiki": wiki, "crm": crm})
    await runner.schemas(["wiki", "crm"])

    outcome = await runner.execute("crm__search", {"q": "acme"})

    # The server is called with its own name for the tool, not the qualified one.
    assert crm.calls == [("search", {"q": "acme"})]
    assert wiki.calls == []
    assert outcome.is_error is False


async def test_a_server_that_is_down_costs_its_tools_not_the_turn():
    """A wiki being unreachable must not take the conversation with it."""
    runner = runner_with(
        {"wiki": FakeTransport([SEARCH], down=True), "crm": FakeTransport([SEARCH])}
    )

    schemas = await runner.schemas(["wiki", "crm"])

    assert [s.name for s in schemas] == ["crm__search"]


async def test_a_failure_at_call_time_is_reported_to_the_model():
    runner = runner_with({"wiki": FakeTransport([SEARCH])})
    await runner.schemas(["wiki"])
    runner._servers._clients["wiki"]._down = True  # noqa: SLF001

    outcome = await runner.execute("wiki__search", {})

    assert outcome.is_error is True
    assert "unreachable" in outcome.text


async def test_an_invented_name_is_refused_rather_than_dispatched():
    runner = runner_with({"wiki": FakeTransport([SEARCH])})
    await runner.schemas(["wiki"])

    outcome = await runner.execute("wiki__delete_everything", {})

    assert outcome.is_error is True
    assert "not available" in outcome.text


async def test_only_the_servers_asked_for_are_offered():
    wiki, crm = FakeTransport([SEARCH]), FakeTransport([SEARCH])
    runner = runner_with({"wiki": wiki, "crm": crm})

    schemas = await runner.schemas(["wiki"])

    assert [s.name for s in schemas] == ["wiki__search"]
    # And the one not asked for cannot be reached by name either.
    assert (await runner.execute("crm__search", {})).is_error is True


async def test_a_tool_name_the_vendor_would_reject_is_made_safe():
    odd = RemoteTool(name="search files (all)", description="", input_schema={})
    runner = runner_with({"wiki": FakeTransport([odd])})

    schemas = await runner.schemas(["wiki"])

    assert schemas[0].name == "wiki__search_files__all_"
    # Still routes back to the server's own spelling.
    await runner.execute(schemas[0].name, {})
    assert runner._servers._clients["wiki"].calls[0][0] == "search files (all)"  # noqa: SLF001


async def test_one_server_cannot_flood_the_window():
    many = [RemoteTool(name=f"t{i}", description="", input_schema={}) for i in range(100)]
    runner = runner_with({"wiki": FakeTransport(many)})

    schemas = await runner.schemas(["wiki"])

    assert len(schemas) == 40
