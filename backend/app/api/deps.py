"""Dependency injection.

Wiring lives here so routers stay thin: a router declares the service it needs
and gets one, already built with a request-scoped session and the shared
clients created at startup.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.embeddings.base import EmbeddingProvider
from app.clients.llm.router import ModelRouter, ProviderRegistry
from app.clients.sandbox.base import Sandbox, SandboxLimits
from app.clients.storage.base import StorageClient
from app.clients.stt.base import TranscriptionClient
from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.core.logging import user_id_var, workspace_id_var
from app.core.security import decode_token
from app.db.rls import set_identity
from app.models.tenancy import User, Workspace
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
from app.services.analysis_service import AnalysisService
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.ingestion_service import IngestionService
from app.services.invitation_service import InvitationService
from app.services.knowledge_service import KnowledgeService
from app.services.membership_service import MembershipService
from app.services.model_service import ModelService
from app.services.project_service import ProjectService
from app.services.rag_service import RAGService
from app.services.suggestion_service import SuggestionService
from app.services.task_resume_service import TaskResumeService
from app.services.team_service import TeamService
from app.services.usage_service import UsageService
from app.services.workspace_service import WorkspaceService

# auto_error=False so a missing header raises our own AuthenticationError and
# comes back in the Problem Details envelope like every other failure.
_bearer = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------
# Infrastructure
# --------------------------------------------------------------------------


def get_config() -> Settings:
    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session per request, rolled back on failure and always closed."""
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_router(request: Request) -> ModelRouter:
    return request.app.state.model_router


def get_storage(request: Request) -> StorageClient:
    return request.app.state.storage


def get_embeddings(request: Request) -> EmbeddingProvider:
    return request.app.state.embeddings


def get_sandbox(request: Request) -> Sandbox | None:
    return request.app.state.sandbox


def get_sandbox_limits(request: Request) -> SandboxLimits:
    return request.app.state.sandbox_limits


def get_transcriber(request: Request) -> TranscriptionClient | None:
    return request.app.state.transcriber


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_config)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]
RouterDep = Annotated[ModelRouter, Depends(get_router)]
StorageDep = Annotated[StorageClient, Depends(get_storage)]
EmbeddingsDep = Annotated[EmbeddingProvider, Depends(get_embeddings)]


# --------------------------------------------------------------------------
# Repositories
# --------------------------------------------------------------------------


def _repo(cls):  # type: ignore[no-untyped-def]
    def factory(session: SessionDep):  # type: ignore[no-untyped-def]
        return cls(session)

    return factory


UsersDep = Annotated[UserRepository, Depends(_repo(UserRepository))]
OrgsDep = Annotated[OrganizationRepository, Depends(_repo(OrganizationRepository))]
TeamsDep = Annotated[TeamRepository, Depends(_repo(TeamRepository))]
MembershipsDep = Annotated[MembershipRepository, Depends(_repo(MembershipRepository))]
WorkspacesDep = Annotated[WorkspaceRepository, Depends(_repo(WorkspaceRepository))]
DocumentsDep = Annotated[DocumentRepository, Depends(_repo(DocumentRepository))]
ChunksDep = Annotated[ChunkRepository, Depends(_repo(ChunkRepository))]
TablesDep = Annotated[DocumentTableRepository, Depends(_repo(DocumentTableRepository))]
ConversationsDep = Annotated[ConversationRepository, Depends(_repo(ConversationRepository))]
MessagesDep = Annotated[MessageRepository, Depends(_repo(MessageRepository))]
RunsDep = Annotated[AnalysisRunRepository, Depends(_repo(AnalysisRunRepository))]
UsageRepoDep = Annotated[UsageRepository, Depends(_repo(UsageRepository))]
VoiceRecordingsDep = Annotated[VoiceRecordingRepository, Depends(_repo(VoiceRecordingRepository))]
InvitationsDep = Annotated[InvitationRepository, Depends(_repo(InvitationRepository))]
ProjectsDep = Annotated[ProjectRepository, Depends(_repo(ProjectRepository))]
TasksDep = Annotated[TaskRepository, Depends(_repo(TaskRepository))]
ClassificationsDep = Annotated[ClassificationRepository, Depends(_repo(ClassificationRepository))]


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    users: UsersDep,
    settings: SettingsDep,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("An access token is required.")

    payload = decode_token(settings=settings, token=credentials.credentials, expected_type="access")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token.") from exc

    user = await users.get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid token.")

    user_id_var.set(str(user.id))
    # Declared here, the moment identity is known, so row-level security can
    # scope every subsequent query in this request.
    set_identity(user_id=user.id)
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------


def get_auth_service(
    settings: SettingsDep,
    users: UsersDep,
    organizations: OrgsDep,
    teams: TeamsDep,
    memberships: MembershipsDep,
    workspaces: WorkspacesDep,
) -> AuthService:
    return AuthService(
        settings=settings,
        users=users,
        organizations=organizations,
        teams=teams,
        memberships=memberships,
        workspaces=workspaces,
    )


def get_membership_service(
    memberships: MembershipsDep, teams: TeamsDep, users: UsersDep
) -> MembershipService:
    return MembershipService(memberships=memberships, teams=teams, users=users)


MembershipServiceDep = Annotated[MembershipService, Depends(get_membership_service)]


def get_team_service(
    teams: TeamsDep,
    memberships: MembershipsDep,
    users: UsersDep,
    organizations: OrgsDep,
    access: MembershipServiceDep,
) -> TeamService:
    return TeamService(
        teams=teams,
        memberships=memberships,
        users=users,
        organizations=organizations,
        membership_service=access,
    )


TeamServiceDep = Annotated[TeamService, Depends(get_team_service)]


def get_invitation_service(
    settings: SettingsDep,
    invitations: InvitationsDep,
    teams: TeamsDep,
    users: UsersDep,
    memberships: MembershipsDep,
    organizations: OrgsDep,
    access: MembershipServiceDep,
) -> InvitationService:
    return InvitationService(
        settings=settings,
        invitations=invitations,
        teams=teams,
        users=users,
        memberships=memberships,
        organizations=organizations,
        membership_service=access,
    )


InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]


def get_project_service(
    projects: ProjectsDep, tasks: TasksDep, access: MembershipServiceDep
) -> ProjectService:
    return ProjectService(projects=projects, tasks=tasks, membership_service=access)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


def get_task_resume_service(
    tasks: TasksDep,
    projects: ProjectsDep,
    conversations: ConversationsDep,
    messages: MessagesDep,
    router: RouterDep,
    project_service: ProjectServiceDep,
) -> TaskResumeService:
    return TaskResumeService(
        tasks=tasks,
        projects=projects,
        conversations=conversations,
        messages=messages,
        router=router,
        project_service=project_service,
    )


TaskResumeServiceDep = Annotated[TaskResumeService, Depends(get_task_resume_service)]


def get_suggestion_service(
    request: Request,
    tasks: TasksDep,
    documents: DocumentsDep,
    conversations: ConversationsDep,
    router: RouterDep,
) -> SuggestionService:
    return SuggestionService(
        tasks=tasks,
        documents=documents,
        conversations=conversations,
        router=router,
        # Suggestions are a digest, not a record: the cache and the
        # last-visit marker both live in Redis, and both degrade to sensible
        # defaults when it is absent.
        redis=getattr(request.app.state, "redis", None),
    )


SuggestionServiceDep = Annotated[SuggestionService, Depends(get_suggestion_service)]


def get_knowledge_service(
    classifications: ClassificationsDep,
    documents: DocumentsDep,
    chunks: ChunksDep,
    router: RouterDep,
) -> KnowledgeService:
    return KnowledgeService(
        classifications=classifications,
        documents=documents,
        chunks=chunks,
        router=router,
    )


KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]


def get_workspace_service(
    workspaces: WorkspacesDep,
    teams: TeamsDep,
    memberships: MembershipsDep,
    documents: DocumentsDep,
    chunks: ChunksDep,
    conversations: ConversationsDep,
    runs: RunsDep,
) -> WorkspaceService:
    return WorkspaceService(
        workspaces=workspaces,
        teams=teams,
        memberships=memberships,
        documents=documents,
        chunks=chunks,
        conversations=conversations,
        analysis_runs=runs,
    )


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


def get_usage_service(usage: UsageRepoDep, registry: RegistryDep) -> UsageService:
    return UsageService(usage=usage, registry=registry)


UsageServiceDep = Annotated[UsageService, Depends(get_usage_service)]


def get_ingestion_service(
    documents: DocumentsDep,
    chunks: ChunksDep,
    tables: TablesDep,
    storage: StorageDep,
    embeddings: EmbeddingsDep,
    router: RouterDep,
    settings: SettingsDep,
) -> IngestionService:
    return IngestionService(
        documents=documents,
        chunks=chunks,
        tables=tables,
        storage=storage,
        embeddings=embeddings,
        router=router,
        ocr_enabled=settings.ocr_fallback_enabled,
        ocr_max_pages=settings.ocr_max_pages,
    )


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]


def get_rag_service(chunks: ChunksDep, embeddings: EmbeddingsDep, router: RouterDep) -> RAGService:
    return RAGService(chunks=chunks, embeddings=embeddings, router=router)


def get_chat_service(
    conversations: ConversationsDep,
    messages: MessagesDep,
    chunks: ChunksDep,
    embeddings: EmbeddingsDep,
    router: RouterDep,
    usage: UsageServiceDep,
) -> ChatService:
    return ChatService(
        conversations=conversations,
        messages=messages,
        rag=RAGService(chunks=chunks, embeddings=embeddings, router=router),
        router=router,
        usage=usage,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def get_analysis_service(
    request: Request,
    runs: RunsDep,
    documents: DocumentsDep,
    tables: TablesDep,
    storage: StorageDep,
    router: RouterDep,
    usage: UsageServiceDep,
) -> AnalysisService:
    return AnalysisService(
        runs=runs,
        documents=documents,
        tables=tables,
        storage=storage,
        sandbox=request.app.state.sandbox,
        limits=request.app.state.sandbox_limits,
        router=router,
        usage=usage,
    )


AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]


def get_model_service(registry: RegistryDep) -> ModelService:
    return ModelService(registry)


# --------------------------------------------------------------------------
# Workspace access
# --------------------------------------------------------------------------


@dataclass(slots=True)
class WorkspaceContext:
    """A workspace the caller has been confirmed to have access to.

    Routers depend on this rather than on a raw path parameter, so no handler
    can act on a workspace id that was never authorised.
    """

    workspace: Workspace
    user: User

    @property
    def id(self) -> uuid.UUID:
        return self.workspace.id

    @property
    def org_id(self) -> uuid.UUID:
        return self.user.org_id

    @property
    def preferred_model(self) -> str | None:
        return self.workspace.preferred_model


async def get_workspace_context(
    workspace_id: uuid.UUID,
    user: CurrentUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceContext:
    workspace = await service.require_access(workspace_id, user.id)
    workspace_id_var.set(str(workspace.id))
    set_identity(workspace_id=workspace.id)
    return WorkspaceContext(workspace=workspace, user=user)


WorkspaceContextDep = Annotated[WorkspaceContext, Depends(get_workspace_context)]
