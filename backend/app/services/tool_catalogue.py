"""The built-in tool catalogue.

Held in code rather than seeded into the database, so a fresh deployment has a
populated registry with no migration data and no fixture to keep in step.

Two of these are real. The rest are **placeholders**: declared so the registry
has shape and the UI can be built against it, and refusing to run rather than
pretending. A tool that silently does nothing is worse than one that says it is
not connected yet — the model would report success it never had.

Each becomes an MCP server when it is connected for real. That is the whole
point of the `kind` column: turning a placeholder into a working integration
should be a config change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.config import McpServerConfig
from app.core.logging import get_logger
from app.models.enums import ToolCategory, ToolKind

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    slug: str
    name: str
    description: str
    category: ToolCategory
    kind: ToolKind
    # Roughly what this tool's schema adds to every request that has it on.
    # Measured for the builtins; estimated for placeholders until they are real.
    context_cost_tokens: int
    enabled_by_default: bool = False
    # The vendor-hosted tool this maps to, when it is one. A provider that
    # does not host it reports the tool as unavailable rather than offering a
    # switch that silently does nothing.
    hosted_tool: str | None = None
    # Vendors known to host it, for the "needs a Claude model" note in the UI.
    providers: tuple[str, ...] = ()


BUILTIN_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        slug="data-explorer",
        name="Data explorer",
        description=(
            "Ask questions of an uploaded spreadsheet. Writes the code, runs it in "
            "an isolated sandbox, and returns both the answer and the program."
        ),
        category=ToolCategory.ANALYTICS,
        kind=ToolKind.BUILTIN,
        context_cost_tokens=420,
        enabled_by_default=True,
    ),
    ToolDefinition(
        slug="workspace-documents",
        name="Workspace documents",
        description=(
            "Search the documents in this workspace and answer from them, with a "
            "citation for every claim."
        ),
        category=ToolCategory.KNOWLEDGE,
        kind=ToolKind.BUILTIN,
        context_cost_tokens=310,
        enabled_by_default=True,
    ),
    # --- not connected yet -------------------------------------------------
    ToolDefinition(
        slug="issue-tracker",
        name="Issue tracker",
        description="Look up issues, sprints, boards and epics.",
        category=ToolCategory.ENGINEERING,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=800,
    ),
    ToolDefinition(
        slug="code-search",
        name="Code intelligence",
        description="Search and review code across your repositories.",
        category=ToolCategory.ENGINEERING,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=650,
    ),
    ToolDefinition(
        slug="wiki",
        name="Wiki",
        description="Read your team's knowledge base.",
        category=ToolCategory.KNOWLEDGE,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=380,
    ),
    ToolDefinition(
        slug="calendar",
        name="Calendar",
        description="Check availability and upcoming meetings.",
        category=ToolCategory.ADMIN,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=300,
    ),
    ToolDefinition(
        slug="staff-directory",
        name="Staff directory",
        description="Find people, their teams, and who reports to whom.",
        category=ToolCategory.ADMIN,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=280,
    ),
    ToolDefinition(
        slug="service-desk",
        name="Service desk",
        description="Query incidents, change requests and problem records.",
        category=ToolCategory.ADMIN,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=520,
    ),
    ToolDefinition(
        slug="web-search",
        name="Web search",
        description=(
            "Search the public web and read the pages it finds. Answers say "
            "which pages they came from, kept separate from your documents."
        ),
        category=ToolCategory.DATA,
        kind=ToolKind.BUILTIN,
        context_cost_tokens=240,
        hosted_tool="web_search",
        providers=("anthropic",),
    ),
    ToolDefinition(
        slug="market-data",
        name="Market data",
        description="Look up prices, filings and company fundamentals.",
        category=ToolCategory.DATA,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=700,
    ),
    ToolDefinition(
        slug="slide-generator",
        name="Slide generator",
        description="Turn an answer into a deck.",
        category=ToolCategory.ANALYTICS,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=460,
    ),
    ToolDefinition(
        slug="database-inventory",
        name="Database inventory",
        description="Look up a database by system id and see who owns it.",
        category=ToolCategory.ENGINEERING,
        kind=ToolKind.PLACEHOLDER,
        context_cost_tokens=350,
    ),
)

BY_SLUG = {tool.slug: tool for tool in BUILTIN_TOOLS}


def catalogue_for(servers: list[McpServerConfig]) -> tuple[ToolDefinition, ...]:
    """The built-ins, plus whatever the operator has connected.

    A configured server whose slug matches a placeholder **replaces** it, which
    is the promise the `kind` column was added for: connecting the wiki is
    setting `MCP_SERVERS`, not editing this file. The placeholder's name,
    description and category carry over where the configuration does not
    override them, so an existing card becomes live rather than being
    duplicated by a second one.

    A slug matching a real built-in is ignored. Those are served in-process and
    a remote server claiming the name would shadow working code — and the
    catalogue is not a place to let configuration override behaviour.
    """
    configured = {server.slug: server for server in servers}
    out: list[ToolDefinition] = []

    for tool in BUILTIN_TOOLS:
        server = configured.pop(tool.slug, None)
        if server is None or tool.kind is not ToolKind.PLACEHOLDER:
            if server is not None:
                log.warning("mcp_server_ignored", server=server.slug, reason="builtin_exists")
            out.append(tool)
            continue
        out.append(
            replace(
                tool,
                name=server.name or tool.name,
                description=server.description or tool.description,
                category=ToolCategory(server.category),
                kind=ToolKind.MCP,
                context_cost_tokens=server.context_cost_tokens,
            )
        )

    # Anything left is an integration the catalogue never anticipated, which is
    # the ordinary case once this is used for real.
    out.extend(
        ToolDefinition(
            slug=server.slug,
            name=server.name,
            description=server.description or "Connected over MCP.",
            category=ToolCategory(server.category),
            kind=ToolKind.MCP,
            context_cost_tokens=server.context_cost_tokens,
        )
        for server in configured.values()
    )
    return tuple(out)
