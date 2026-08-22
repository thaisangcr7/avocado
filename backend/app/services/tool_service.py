"""The tool registry, and what having tools switched on costs.

The catalogue is static; what varies is which tools a conversation has enabled
and what that spends. Every enabled tool's schema rides along on every request
whether or not the model calls it, so the total is reported rather than left to
be discovered as gradually worse answers.
"""

from __future__ import annotations

import uuid

from app.clients.llm.router import ModelRouter, TaskType
from app.core.errors import AvocadoError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import ToolKind
from app.repositories.tools import ConversationToolRepository
from app.schemas.tools import ToolResponse, ToolSelectionResponse
from app.services.tool_catalogue import BUILTIN_TOOLS, BY_SLUG, ToolDefinition

log = get_logger(__name__)

# The share of a model's window that enabled tools may occupy before the UI
# says so. Past roughly a tenth, the schemas are crowding out the conversation
# they exist to serve.
TOOL_BUDGET_WARN_FRACTION = 0.1


def _runnable(tool: ToolDefinition, hosted: frozenset[str]) -> bool:
    """Whether the answering model's vendor can actually run this tool.

    Web search is hosted by the vendor, so a workspace pinned to one without it
    would switch the tool on and get nothing. Reporting it as off there is the
    difference between a control that is unavailable and one that lies.

    The provider declares what it hosts; nothing here matches on a vendor name.
    """
    if not tool.hosted_tool:
        return True
    return tool.hosted_tool in hosted


class ToolService:
    def __init__(
        self, *, selections: ConversationToolRepository, router: ModelRouter | None = None
    ) -> None:
        self._selections = selections
        self._router = router

    async def _require_conversation(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> None:
        """Reads as absent rather than forbidden, like every other scoped route."""
        if not await self._selections.belongs_to_workspace(conversation_id, workspace_id):
            raise NotFoundError("Conversation not found.")

    def _hosted_tools(self, preferred_model: str | None) -> frozenset[str]:
        """Server-side tools the model that would answer right now can run.

        An unresolvable model reports none rather than guessing, so a tool is
        shown as unavailable instead of promising something unverified.
        """
        if self._router is None:
            return frozenset()
        try:
            provider, _ = self._router.resolve(
                task=TaskType.SYNTHESIS, preferred_model=preferred_model
            )
        except AvocadoError:
            return frozenset()
        return provider.server_tools

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
        hosted = self._hosted_tools(preferred_model)

        # No decisions recorded means the defaults are in force. Once anything
        # has been chosen the recorded set is authoritative, including when it
        # is empty — turning everything off has to survive a reload.
        if choices:
            enabled = {slug for slug, on in choices.items() if on}
        else:
            enabled = {t.slug for t in BUILTIN_TOOLS if t.enabled_by_default}

        tools = [
            ToolResponse(
                slug=tool.slug,
                name=tool.name,
                description=tool.description,
                category=tool.category,
                kind=tool.kind,
                context_cost_tokens=tool.context_cost_tokens,
                enabled=tool.slug in enabled and _runnable(tool, hosted),
                connected=tool.kind is not ToolKind.PLACEHOLDER,
                runs_on=sorted(tool.providers),
            )
            for tool in BUILTIN_TOOLS
        ]

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

        unknown = [slug for slug in slugs if slug not in BY_SLUG]
        if unknown:
            raise NotFoundError(f"Unknown tool: {unknown[0]}.")

        # A placeholder is declared but not wired to anything. Letting one be
        # switched on would put a tool in front of the model that reports
        # success it never had, which is worse than not offering it.
        not_connected = [slug for slug in slugs if BY_SLUG[slug].kind is ToolKind.PLACEHOLDER]
        if not_connected:
            raise ValidationError(
                f"'{BY_SLUG[not_connected[0]].name}' is not connected yet, so it "
                "cannot be switched on."
            )

        # A row per catalogue entry, so the absence of rows keeps meaning
        # "never configured" rather than "everything off".
        wanted = set(slugs)
        await self._selections.replace(
            conversation_id=conversation_id,
            choices={tool.slug: tool.slug in wanted for tool in BUILTIN_TOOLS},
        )
        await self._selections.commit()
        log.info("tools_selected", conversation_id=str(conversation_id), count=len(slugs))
        return await self.catalogue(conversation_id, workspace_id, preferred_model=preferred_model)
