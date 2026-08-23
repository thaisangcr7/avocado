"""The tool registry, and what having tools switched on costs.

The catalogue is static; what varies is which tools a conversation has enabled
and what that spends. Every enabled tool's schema rides along on every request
whether or not the model calls it, so the total is reported rather than left to
be discovered as gradually worse answers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.clients.llm.router import ModelRouter, TaskType
from app.clients.tools.registry import McpServers, ServerListing
from app.core.errors import AvocadoError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import ToolKind
from app.repositories.tools import ConversationToolRepository
from app.schemas.tools import ToolResponse, ToolSelectionResponse
from app.services.tool_catalogue import ToolDefinition, catalogue_for
from app.services.tool_runner import measure_cost

log = get_logger(__name__)

# The share of a model's window that enabled tools may occupy before the UI
# says so. Past roughly a tenth, the schemas are crowding out the conversation
# they exist to serve.
TOOL_BUDGET_WARN_FRACTION = 0.1


@dataclass(frozen=True, slots=True)
class _Capabilities:
    """What the model that would answer right now can actually do."""

    hosted: frozenset[str] = frozenset()
    client_tools: bool = False


def _runnable(tool: ToolDefinition, can: _Capabilities) -> bool:
    """Whether the answering model's vendor can actually run this tool.

    Two ways a tool can be switched on and do nothing, and both are reported as
    off instead. Web search is hosted by the vendor, so a workspace pinned to
    one without it would get silence. An MCP tool needs a vendor that runs a
    tool loop at all, which is a different capability and a separate check.

    The provider declares both; nothing here matches on a vendor name.
    """
    if tool.kind is ToolKind.MCP and not can.client_tools:
        return False
    if not tool.hosted_tool:
        return True
    return tool.hosted_tool in can.hosted


class ToolService:
    def __init__(
        self,
        *,
        selections: ConversationToolRepository,
        router: ModelRouter | None = None,
        servers: McpServers | None = None,
    ) -> None:
        self._selections = selections
        self._router = router
        self._servers = servers
        self._catalogue = catalogue_for(servers.configs if servers else [])
        self._by_slug = {tool.slug: tool for tool in self._catalogue}

    async def _require_conversation(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> None:
        """Reads as absent rather than forbidden, like every other scoped route."""
        if not await self._selections.belongs_to_workspace(conversation_id, workspace_id):
            raise NotFoundError("Conversation not found.")

    def _capabilities(self, preferred_model: str | None) -> _Capabilities:
        """What the model that would answer right now can run.

        An unresolvable model reports nothing rather than guessing, so a tool is
        shown as unavailable instead of promising something unverified.
        """
        if self._router is None:
            return _Capabilities()
        try:
            provider, _ = self._router.resolve(
                task=TaskType.SYNTHESIS, preferred_model=preferred_model
            )
        except AvocadoError:
            return _Capabilities()
        return _Capabilities(
            hosted=provider.server_tools,
            client_tools=provider.supports_client_tools,
        )

    async def _health(self) -> dict[str, ServerListing]:
        """Probe every connected server. Nothing configured means no probing."""
        if self._servers is None:
            return {}
        remote = [t.slug for t in self._catalogue if t.kind is ToolKind.MCP]
        return await self._servers.listings(remote)

    async def catalogue(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        preferred_model: str | None = None,
    ) -> ToolSelectionResponse:
        """Every tool, with which are on for this conversation and what they cost."""
        await self._require_conversation(conversation_id, workspace_id)
        choices = await self._selections.choices(conversation_id)
        can = self._capabilities(preferred_model)

        # No decisions recorded means the defaults are in force. Once anything
        # has been chosen the recorded set is authoritative, including when it
        # is empty — turning everything off has to survive a reload.
        if choices:
            enabled = {slug for slug, on in choices.items() if on}
        else:
            enabled = {t.slug for t in self._catalogue if t.enabled_by_default}

        # One probe per connected server, cached and run concurrently. It
        # answers two questions at once: whether the server is answering, and
        # what its schemas actually cost.
        health = await self._health()

        tools = []
        for tool in self._catalogue:
            listing = health.get(tool.slug)
            cost = tool.context_cost_tokens
            if listing is not None and listing.reachable:
                cost = measure_cost(listing.tools, tool.slug) or cost
            tools.append(
                ToolResponse(
                    slug=tool.slug,
                    name=tool.name,
                    description=tool.description,
                    category=tool.category,
                    kind=tool.kind,
                    context_cost_tokens=cost,
                    enabled=tool.slug in enabled and _runnable(tool, can),
                    connected=tool.kind is not ToolKind.PLACEHOLDER,
                    runs_on=sorted(tool.providers),
                    # None for anything that is not a remote server: a built-in
                    # has no separate thing to be reachable.
                    reachable=listing.reachable if listing is not None else None,
                    tool_count=len(listing.tools) if listing is not None else None,
                )
            )

        return ToolSelectionResponse(
            tools=tools,
            enabled_count=sum(1 for t in tools if t.enabled),
            context_cost_tokens=sum(t.context_cost_tokens for t in tools if t.enabled),
        )

    async def set_enabled(
        self,
        *,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        slugs: list[str],
        preferred_model: str | None = None,
    ) -> ToolSelectionResponse:
        await self._require_conversation(conversation_id, workspace_id)

        unknown = [slug for slug in slugs if slug not in self._by_slug]
        if unknown:
            raise NotFoundError(f"Unknown tool: {unknown[0]}.")

        # A placeholder is declared but not wired to anything. Letting one be
        # switched on would put a tool in front of the model that reports
        # success it never had, which is worse than not offering it.
        not_connected = [slug for slug in slugs if self._by_slug[slug].kind is ToolKind.PLACEHOLDER]
        if not_connected:
            raise ValidationError(
                f"'{self._by_slug[not_connected[0]].name}' is not connected yet, so it "
                "cannot be switched on."
            )

        # A row per catalogue entry, so the absence of rows keeps meaning
        # "never configured" rather than "everything off".
        wanted = set(slugs)
        await self._selections.replace(
            conversation_id=conversation_id,
            choices={tool.slug: tool.slug in wanted for tool in self._catalogue},
        )
        await self._selections.commit()
        log.info("tools_selected", conversation_id=str(conversation_id), count=len(slugs))
        return await self.catalogue(conversation_id, workspace_id, preferred_model=preferred_model)
