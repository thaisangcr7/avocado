"""SQLAlchemy models.

Imported as a package so Alembic autogenerate sees every table on `Base`.
"""

from app.models.analysis import AnalysisRun
from app.models.artifacts import Artifact
from app.models.conversations import Conversation, Message
from app.models.documents import Document, DocumentChunk, DocumentTable
from app.models.enums import (
    AnalysisStatus,
    ArtifactAuthor,
    ArtifactKind,
    DocumentKind,
    DocumentStatus,
    DocumentType,
    MessageRole,
    ProjectStatus,
    ProjectVisibility,
    Role,
    SuggestionKind,
    TaskStatus,
    ToolCategory,
    ToolKind,
    TranscriptStatus,
)
from app.models.feedback import MessageFeedback
from app.models.invitations import Invitation, InvitationStatus
from app.models.knowledge import DocumentClassification
from app.models.notifications import Notification
from app.models.presets import Preset, PresetPin, PresetShare
from app.models.projects import Project, ProjectMember, Task
from app.models.schedules import Schedule
from app.models.tenancy import Organization, Team, TeamMembership, User, Workspace
from app.models.tools import ConversationTool
from app.models.usage import ApiUsageLog
from app.models.voice import VoiceRecording

__all__ = [
    "AnalysisRun",
    "AnalysisStatus",
    "ApiUsageLog",
    "Artifact",
    "ArtifactAuthor",
    "ArtifactKind",
    "Conversation",
    "ConversationTool",
    "Document",
    "DocumentChunk",
    "DocumentClassification",
    "DocumentKind",
    "DocumentStatus",
    "DocumentTable",
    "DocumentType",
    "Invitation",
    "InvitationStatus",
    "Message",
    "MessageFeedback",
    "MessageRole",
    "Notification",
    "Organization",
    "Preset",
    "PresetPin",
    "PresetShare",
    "Project",
    "ProjectMember",
    "ProjectStatus",
    "ProjectVisibility",
    "Role",
    "Schedule",
    "SuggestionKind",
    "Task",
    "TaskStatus",
    "Team",
    "TeamMembership",
    "ToolCategory",
    "ToolKind",
    "TranscriptStatus",
    "User",
    "VoiceRecording",
    "Workspace",
]
