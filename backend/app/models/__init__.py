"""SQLAlchemy models.

Imported as a package so Alembic autogenerate sees every table on `Base`.
"""

from app.models.analysis import AnalysisRun
from app.models.conversations import Conversation, Message
from app.models.documents import Document, DocumentChunk, DocumentTable
from app.models.enums import (
    AnalysisStatus,
    DocumentStatus,
    DocumentType,
    MessageRole,
    ProjectStatus,
    ProjectVisibility,
    Role,
    TaskStatus,
    TranscriptStatus,
)
from app.models.projects import Project, ProjectMember, Task
from app.models.tenancy import Organization, Team, TeamMembership, User, Workspace
from app.models.usage import ApiUsageLog
from app.models.voice import VoiceRecording

__all__ = [
    "AnalysisRun",
    "AnalysisStatus",
    "ApiUsageLog",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "DocumentTable",
    "DocumentType",
    "Message",
    "MessageRole",
    "Organization",
    "Project",
    "ProjectMember",
    "ProjectStatus",
    "ProjectVisibility",
    "Role",
    "Task",
    "TaskStatus",
    "Team",
    "TeamMembership",
    "TranscriptStatus",
    "User",
    "VoiceRecording",
    "Workspace",
]
