"""Repositories — the only layer that talks to SQLAlchemy."""

from app.repositories.analysis import AnalysisRunRepository
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)
from app.repositories.invitations import InvitationRepository
from app.repositories.knowledge import ClassificationRepository
from app.repositories.projects import ProjectRepository, TaskRepository
from app.repositories.tenancy import (
    MembershipRepository,
    OrganizationRepository,
    TeamRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.repositories.usage import UsageRepository
from app.repositories.voice import VoiceRecordingRepository

__all__ = [
    "AnalysisRunRepository",
    "ChunkRepository",
    "ClassificationRepository",
    "ConversationRepository",
    "DocumentRepository",
    "DocumentTableRepository",
    "InvitationRepository",
    "MembershipRepository",
    "MessageRepository",
    "OrganizationRepository",
    "ProjectRepository",
    "TaskRepository",
    "TeamRepository",
    "UsageRepository",
    "UserRepository",
    "VoiceRecordingRepository",
    "WorkspaceRepository",
]
