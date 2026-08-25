"""Dependency injection.

Wiring lives here so routers stay thin: a router declares the service it needs
and gets one, already built with a request-scoped session and the shared
clients created at startup.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.embeddings.base import EmbeddingProvider
from app.clients.llm.router import (
    BUDGET_SOFT_THRESHOLD,
    BudgetState,
    ModelRouter,
    ProviderRegistry,
)
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
from app.repositories.artifacts import ArtifactRepository
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)
from app.repositories.feedback import MessageFeedbackRepository
from app.repositories.invitations import InvitationRepository
from app.repositories.knowledge import ClassificationRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.presets import (
    PresetPinRepository,
    PresetRepository,
    PresetShareRepository,
)
from app.repositories.projects import ProjectRepository, TaskRepository
from app.repositories.schedules import ScheduleRepository
from app.repositories.tenancy import (
    MembershipRepository,
    OrganizationRepository,
    TeamRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.repositories.tools import ConversationToolRepository
from app.repositories.usage import UsageRepository
from app.repositories.voice import VoiceRecordingRepository
from app.services.analysis_service import AnalysisService
from app.services.artifact_service import ArtifactService
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.enhance_service import EnhanceService
from app.services.ingestion_service import IngestionService
from app.services.invitation_service import InvitationService
from app.services.knowledge_service import KnowledgeService
from app.services.membership_service import MembershipService
from app.services.model_service import ModelService
from app.services.notification_service import NotificationService
from app.services.preset_service import PresetService
from app.services.project_service import ProjectService
from app.services.rag_service import RAGService
from app.services.report_service import ReportService
from app.services.schedule_service import ScheduleService
from app.services.suggestion_service import SuggestionService
from app.services.task_resume_service import TaskResumeService
from app.services.team_service import TeamService
from app.services.tool_service import ToolService
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
PresetsDep = Annotated[PresetRepository, Depends(_repo(PresetRepository))]
FeedbackDep = Annotated[MessageFeedbackRepository, Depends(_repo(MessageFeedbackRepository))]
SchedulesDep = Annotated[ScheduleRepository, Depends(_repo(ScheduleRepository))]
NotificationsDep = Annotated[NotificationRepository, Depends(_repo(NotificationRepository))]
PresetPinsDep = Annotated[PresetPinRepository, Depends(_repo(PresetPinRepository))]
PresetSharesDep = Annotated[PresetShareRepository, Depends(_repo(PresetShareRepository))]
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
ArtifactsDep = Annotated[ArtifactRepository, Depends(_repo(ArtifactRepository))]
ConversationToolsDep = Annotated[
    ConversationToolRepository, Depends(_repo(ConversationToolRepository))
]
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


# Budget and the router that respects it are declared here, below the
# dependencies they consume: the budget is a property of the authenticated
# caller's organization, so it cannot be resolved any earlier than identity.


async def get_budget_state(user: CurrentUserDep, usage: UsageRepoDep, orgs: OrgsDep) -> BudgetState:
    """Where this organization sits against its monthly ceiling.

    Read once per request and handed to the router, so every call site that
    resolves a model inherits the same decision without reaching for the
    database itself.
    """
    org = await orgs.get(user.org_id)
    ceiling = org.monthly_budget_usd if org else None
    if not ceiling or ceiling <= 0:
        return BudgetState.OK

    spent = await usage.month_to_date_cost(user.org_id, now=datetime.now(UTC))
    if spent >= ceiling:
        return BudgetState.EXHAUSTED
    if spent >= ceiling * BUDGET_SOFT_THRESHOLD:
        return BudgetState.CONSTRAINED
    return BudgetState.OK


BudgetStateDep = Annotated[BudgetState, Depends(get_budget_state)]


def get_router(request: Request, budget: BudgetStateDep) -> ModelRouter:
    """A router bound to this request's budget standing.

    The registry it wraps is shared; only the budget decision is per-request,
    and building a router around it is far cheaper than a database read inside
    every model resolution.
    """
    return ModelRouter(request.app.state.registry, budget=budget)


RouterDep = Annotated[ModelRouter, Depends(get_router)]


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


def get_preset_service(
    presets: PresetsDep,
    pins: PresetPinsDep,
    shares: PresetSharesDep,
    users: UsersDep,
    access: MembershipServiceDep,
) -> PresetService:
    return PresetService(presets=presets, pins=pins, shares=shares, users=users, access=access)


PresetServiceDep = Annotated[PresetService, Depends(get_preset_service)]


def get_schedule_service(schedules: SchedulesDep, presets: PresetsDep) -> ScheduleService:
    return ScheduleService(schedules=schedules, presets=presets)


ScheduleServiceDep = Annotated[ScheduleService, Depends(get_schedule_service)]


def get_enhance_service(router: RouterDep) -> EnhanceService:
    return EnhanceService(router=router)


EnhanceServiceDep = Annotated[EnhanceService, Depends(get_enhance_service)]


def get_notification_service(notifications: NotificationsDep) -> NotificationService:
    return NotificationService(notifications=notifications)


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


def get_artifact_service(artifacts: ArtifactsDep, router: RouterDep) -> ArtifactService:
    return ArtifactService(artifacts=artifacts, router=router)


ArtifactServiceDep = Annotated[ArtifactService, Depends(get_artifact_service)]


def get_tool_service(
    request: Request, selections: ConversationToolsDep, router: RouterDep
) -> ToolService:
    # From app state, not the settings singleton, so the registry and the
    # answer path always read the same list — a picker built from one set of
    # servers and a turn executed against another is the exact disagreement
    # this whole surface exists to avoid.
    return ToolService(selections=selections, router=router, servers=request.app.state.mcp_servers)


ToolServiceDep = Annotated[ToolService, Depends(get_tool_service)]


def get_team_service(
    teams: TeamsDep,
    memberships: MembershipsDep,
    users: UsersDep,
    organizations: OrgsDep,
    usage: UsageRepoDep,
    access: MembershipServiceDep,
) -> TeamService:
    return TeamService(
        teams=teams,
        memberships=memberships,
        users=users,
        usage=usage,
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
    request: Request,
    conversations: ConversationsDep,
    messages: MessagesDep,
    documents: DocumentsDep,
    tables: TablesDep,
    runs: RunsDep,
    storage: StorageDep,
    chunks: ChunksDep,
    embeddings: EmbeddingsDep,
    router: RouterDep,
    usage: UsageServiceDep,
    tools: ConversationToolsDep,
    presets: PresetsDep,
    pins: PresetPinsDep,
    shares: PresetSharesDep,
    users: UsersDep,
    access: MembershipServiceDep,
    feedback: FeedbackDep,
) -> ChatService:
    return ChatService(
        conversations=conversations,
        messages=messages,
        documents=documents,
        tools=tools,
        servers=request.app.state.mcp_servers,
        presets=PresetService(
            presets=presets, pins=pins, shares=shares, users=users, access=access
        ),
        feedback=feedback,
        rag=RAGService(chunks=chunks, embeddings=embeddings, router=router),
        analysis=AnalysisService(
            runs=runs,
            documents=documents,
            tables=tables,
            storage=storage,
            sandbox=request.app.state.sandbox,
            limits=request.app.state.sandbox_limits,
            router=router,
            usage=usage,
        ),
        report=ReportService(
            tables=tables,
            storage=storage,
            sandbox=request.app.state.sandbox,
            limits=request.app.state.sandbox_limits,
            router=router,
            usage=usage,
        ),
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
    artifacts: ArtifactServiceDep,
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
        artifacts=artifacts,
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

    @property
    def require_grounding(self) -> bool:
        return self.workspace.require_grounding


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
