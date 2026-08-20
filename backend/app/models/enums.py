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
