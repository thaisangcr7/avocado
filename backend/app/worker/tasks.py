"""Background jobs.

Each job builds its own session and its own repositories. A job cannot borrow
the request's session: the request has already returned by the time the job
runs, and its session is closed.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.clients.embeddings.base import EmbeddingProvider
from app.clients.llm.router import ModelRouter
from app.clients.storage.base import StorageClient
from app.core.logging import get_logger
from app.db.session import session_scope
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)
from app.services.ingestion_service import IngestionService

log = get_logger(__name__)


async def ingest_document(
    *,
    session_factory: Any,
    storage: StorageClient,
    embeddings: EmbeddingProvider,
    router: ModelRouter,
    document_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Parse, chunk, embed and persist one document."""
    async with session_scope(session_factory) as session:
        documents = DocumentRepository(session)
        document = await documents.get_scoped(document_id, workspace_id)
        if document is None:
            log.warning(
                "ingest_document_missing",
                document_id=str(document_id),
                workspace_id=str(workspace_id),
            )
            return

        service = IngestionService(
            documents=documents,
            chunks=ChunkRepository(session),
            tables=DocumentTableRepository(session),
            storage=storage,
            embeddings=embeddings,
            router=router,
        )
        await service.process(document)


async def arq_ingest_document(ctx: dict[str, Any], document_id: str, workspace_id: str) -> None:
    """Arq entry point. Resources come from the worker's startup context."""
    await ingest_document(
        session_factory=ctx["session_factory"],
        storage=ctx["storage"],
        embeddings=ctx["embeddings"],
        router=ctx["model_router"],
        document_id=uuid.UUID(document_id),
        workspace_id=uuid.UUID(workspace_id),
    )
