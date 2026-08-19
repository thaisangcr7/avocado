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
from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.core.logging import user_id_var, workspace_id_var
from app.core.security import decode_token
from app.models.tenancy import User, Workspace
from app.repositories.analysis import AnalysisRunRepository
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)
from app.repositories.tenancy import (
    MembershipRepository,
    OrganizationRepository,
    TeamRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.repositories.usage import UsageRepository
from app.services.analysis_service import AnalysisService
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.ingestion_service import IngestionService
from app.services.model_service import ModelService
from app.services.rag_service import RAGService
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
) -> IngestionService:
    return IngestionService(
        documents=documents,
        chunks=chunks,
        tables=tables,
        storage=storage,
        embeddings=embeddings,
        router=router,
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
    return WorkspaceContext(workspace=workspace, user=user)


WorkspaceContextDep = Annotated[WorkspaceContext, Depends(get_workspace_context)]
