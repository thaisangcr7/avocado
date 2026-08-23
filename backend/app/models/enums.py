"""Domain enumerations, shared by ORM models and Pydantic schemas."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ORG_ADMIN = "org_admin"
    TEAM_ADMIN = "team_admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def at_least(self, other: Role) -> bool:
        return self.rank >= other.rank


_ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.TEAM_ADMIN: 2,
    Role.ORG_ADMIN: 3,
}


class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    IMAGE = "image"
    TEXT = "text"
    MARKDOWN = "markdown"
    AUDIO = "audio"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TranscriptStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class DocumentKind(StrEnum):
    """What a document *is* to the team, as opposed to what file type it has.

    This is the org knowledge layer (architecture §5): the difference between
    "a pile of uploaded PDFs" and "a queryable map of what this team does".
    """

    POLICY = "policy"
    PROCESS = "process"
    PROJECT = "project"
    REFERENCE = "reference"
    OTHER = "other"


class SuggestionKind(StrEnum):
    """Why a nudge is being shown. Drives its icon and its ordering."""

    TASK_DUE = "task_due"
    TASK_OVERDUE = "task_overdue"
    TASK_BLOCKED = "task_blocked"
    NEW_DOCUMENT = "new_document"
    UNFINISHED_THREAD = "unfinished_thread"
    FAILED_DOCUMENT = "failed_document"


class ProjectVisibility(StrEnum):
    """Who can see a project's tasks.

    `RESTRICTED` is the default: assignee + project members + admins. Opening a
    board to the whole workspace is an explicit opt-in, never inherited from
    document visibility. (Architecture §11.)
    """

    RESTRICTED = "restricted"
    WORKSPACE = "workspace"


class ArtifactKind(StrEnum):
    """What an artifact is, which decides how it is rendered.

    `HTML` is the interesting one and the reason the renderer is sandboxed: it
    is written by a model from the user's own documents, so it is untrusted
    input that happens to be markup.
    """

    HTML = "html"
    MARKDOWN = "markdown"
    CODE = "code"
    CHART = "chart"
    TABLE = "table"


class ArtifactAuthor(StrEnum):
    """Who produced a version. A user edit and a model edit are both versions,
    and telling them apart is what makes the history readable."""

    AI = "ai"
    USER = "user"


class FeedbackRating(StrEnum):
    """What a reader thought of one answer.

    Two values, not five. A scale invites the middle, and the middle says
    nothing that can be acted on — the useful question is whether this answer
    was good enough to keep.
    """

    UP = "up"
    DOWN = "down"


class PresetScope(StrEnum):
    """Who can see a preset.

    Deliberately not "public": `PUBLISHED` still stops at the organisation
    boundary. A preset is a system prompt, which is the most sensitive thing a
    team writes into this product — it encodes how they work and what they care
    about — and no scope here crosses a tenant.

    `PRIVATE` is the author's own, plus anyone it has been shared with by name.
    `ORG` is everyone in the organisation. `PUBLISHED` is `ORG` plus a claim
    that it is worth other people's attention, which is what the Community tab
    lists.
    """

    PRIVATE = "private"
    ORG = "org"
    PUBLISHED = "published"


class ToolCategory(StrEnum):
    """Which tab an integration appears under."""

    ANALYTICS = "analytics"
    ENGINEERING = "engineering"
    KNOWLEDGE = "knowledge"
    ADMIN = "admin"
    DATA = "data"


class ToolKind(StrEnum):
    """How a tool is reached.

    `BUILTIN` is served in-process by this application. `MCP` is a Model Context
    Protocol server, which is the shape every future integration should take —
    a connector then costs a config row rather than a branch in this codebase.
    `PLACEHOLDER` is declared but not yet connected: it appears in the registry
    and refuses to run, rather than pretending to work.
    """

    BUILTIN = "builtin"
    MCP = "mcp"
    PLACEHOLDER = "placeholder"
