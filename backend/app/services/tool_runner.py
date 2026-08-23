"""Turning the MCP servers a conversation has switched on into callable tools.

Two jobs, both about names. A model is shown one flat list of tools and asks
for one by name, so every name must say which server it belongs to — two
servers may each offer `search`. And when the model asks, the name has to lead
back to the server that owns it.

Nothing here knows what any particular integration does. That is the point: a
wiki and an issue tracker take the same path, and neither appears in this file.
"""

from __future__ import annotations

import re

from app.clients.llm.base import ToolOutcome, ToolSchema
from app.clients.tools.base import ToolTransportError
from app.clients.tools.registry import McpServers
from app.core.logging import get_logger

log = get_logger(__name__)

# Vendors constrain tool names to this. A server free to name a tool anything
# would otherwise produce a request the API rejects for the whole turn.
_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]")

# Server slugs are validated to lowercase letters, digits and dashes, so this
# separator cannot occur in one and the split is unambiguous.
SEPARATOR = "__"

# No one server may flood the list. A server offering hundreds of tools would
# spend the window the conversation needs, and the cost shown in the picker was
# measured against something far smaller.
MAX_TOOLS_PER_SERVER = 40


def qualify(slug: str, tool: str) -> str:
    return f"{slug}{SEPARATOR}{_UNSAFE.sub('_', tool)}"


class ToolRunner:
    """The tools a set of enabled servers offers, and the way back to them."""

    def __init__(self, servers: McpServers) -> None:
        self._servers = servers
        # Rebuilt per turn: which tools a server offers can change between one
        # question and the next, and a stale name is a call that fails.
        self._owners: dict[str, tuple[str, str]] = {}

    async def schemas(self, slugs: list[str]) -> list[ToolSchema]:
        """Every tool the named servers offer, named so the model can pick one.

        A server that cannot be reached contributes nothing and does not fail
        the turn. The alternative is a wiki being down taking the conversation
        with it — and the model answers without that tool rather than claiming
        it used one.
        """
        out: list[ToolSchema] = []
        for slug in slugs:
            transport = self._servers.transport(slug)
            if transport is None:
                continue
            try:
                offered = await transport.list_tools()
            except ToolTransportError as exc:
                log.warning("mcp_tools_unavailable", server=slug, detail=exc.detail)
                continue

            for tool in offered[:MAX_TOOLS_PER_SERVER]:
                name = qualify(slug, tool.name)
                self._owners[name] = (slug, tool.name)
                out.append(
                    ToolSchema(
                        name=name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                    )
                )
            if len(offered) > MAX_TOOLS_PER_SERVER:
                log.warning("mcp_tools_capped", server=slug, offered=len(offered))

        return out

    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        """Run one tool, on whichever server owns the name."""
        owner = self._owners.get(name)
        if owner is None:
            # Only reachable if the model invents a name, since it is offered
            # exactly the ones recorded above.
            log.warning("mcp_tool_unknown", tool=name)
            return ToolOutcome(text=f"'{name}' is not available.", is_error=True)

        slug, tool_name = owner
        transport = self._servers.transport(slug)
        if transport is None:
            return ToolOutcome(text=f"'{slug}' is not available.", is_error=True)

        try:
            result = await transport.call(tool_name, arguments)
        except ToolTransportError as exc:
            # Reported to the model rather than raised: it can say it could not
            # reach the system, which is better than the turn failing outright.
            return ToolOutcome(text=exc.detail, is_error=True)

        return ToolOutcome(text=result.text, is_error=result.is_error)
