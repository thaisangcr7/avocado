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
from app.clients.stt.base import TranscriptionClient
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.rls import set_identity
from app.db.session import session_scope
from app.models.enums import DocumentStatus
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)
from app.repositories.knowledge import ClassificationRepository
from app.repositories.tenancy import WorkspaceRepository
from app.repositories.voice import VoiceRecordingRepository
from app.services.ingestion_service import IngestionService
from app.services.knowledge_service import KnowledgeService
from app.services.voice_service import VoiceService

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
    # A job has no user, but it does have exactly one workspace — which is a
    # real scope, not a bypass.
    set_identity(workspace_id=workspace_id)

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

        _settings = get_settings()
        chunks = ChunkRepository(session)
        service = IngestionService(
            documents=documents,
            chunks=chunks,
            tables=DocumentTableRepository(session),
            storage=storage,
            embeddings=embeddings,
            router=router,
            ocr_enabled=_settings.ocr_fallback_enabled,
            ocr_max_pages=_settings.ocr_max_pages,
        )
        await service.process(document)

        # Tagging runs here so a document joins the knowledge map without
        # anyone having to ask. It is best-effort by design: an unclassified
        # document is still a perfectly good, fully retrievable document, and
        # failing the ingest over a missing tag would be the wrong trade.
        if document.status is DocumentStatus.READY:
            await _classify_quietly(
                session=session,
                documents=documents,
                chunks=chunks,
                router=router,
                document_id=document_id,
                workspace_id=workspace_id,
            )


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


async def transcribe_recording(
    *,
    session_factory: Any,
    storage: StorageClient,
    embeddings: EmbeddingProvider,
    router: ModelRouter,
    transcriber: TranscriptionClient | None,
    max_audio_bytes: int,
    recording_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Transcribe a recording, then ingest the transcript it produced.

    Both halves run in one job because a transcript that exists but was never
    chunked is invisible to retrieval — which, from the user's point of view,
    means the recording did not work.
    """
    set_identity(workspace_id=workspace_id)

    async with session_scope(session_factory) as session:
        documents = DocumentRepository(session)
        voice = VoiceService(
            recordings=VoiceRecordingRepository(session),
            documents=documents,
            storage=storage,
            transcriber=transcriber,
            max_audio_bytes=max_audio_bytes,
        )
        document = await voice.transcribe(recording_id, workspace_id)
        if document is None:
            return

        _settings = get_settings()
        chunks = ChunkRepository(session)
        ingestion = IngestionService(
            documents=documents,
            chunks=chunks,
            tables=DocumentTableRepository(session),
            storage=storage,
            embeddings=embeddings,
            router=router,
            ocr_enabled=_settings.ocr_fallback_enabled,
            ocr_max_pages=_settings.ocr_max_pages,
        )
        await ingestion.process(document)

        # A transcript is a document like any other, so it joins the knowledge
        # map the same way an uploaded file does. Without this, a meeting
        # recording is retrievable but invisible to "what does this team do?".
        if document.status is DocumentStatus.READY:
            await _classify_quietly(
                session=session,
                documents=documents,
                chunks=chunks,
                router=router,
                document_id=document.id,
                workspace_id=workspace_id,
            )


async def arq_transcribe_recording(
    ctx: dict[str, Any], recording_id: str, workspace_id: str
) -> None:
    await transcribe_recording(
        session_factory=ctx["session_factory"],
        storage=ctx["storage"],
        embeddings=ctx["embeddings"],
        router=ctx["model_router"],
        transcriber=ctx["transcriber"],
        max_audio_bytes=ctx["settings"].max_audio_bytes,
        recording_id=uuid.UUID(recording_id),
        workspace_id=uuid.UUID(workspace_id),
    )


async def _classify_quietly(
    *,
    session: Any,
    documents: DocumentRepository,
    chunks: ChunkRepository,
    router: ModelRouter,
    document_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Tag a freshly ingested document, swallowing any failure."""
    try:
        team_id = await WorkspaceRepository(session).get_team_id(workspace_id)
        knowledge = KnowledgeService(
            classifications=ClassificationRepository(session),
            documents=documents,
            chunks=chunks,
            router=router,
        )
        await knowledge.classify_document(
            document_id=document_id, workspace_id=workspace_id, team_id=team_id
        )
    except Exception:
        log.debug("post_ingest_classification_skipped", exc_info=True)


async def run_due_schedules(
    *,
    session_factory: Any,
    model_router: ModelRouter,
    embeddings: EmbeddingProvider,
) -> int:
    """Run every schedule whose time has come. Returns how many fired.

    Each one opens a conversation and sends its prompt, so the answer lands
    exactly where every other answer lands — in history, with its citations,
    readable later. A scheduled answer is not a special kind of object.

    One schedule failing must not stop the sweep. A broken prompt in one
    workspace would otherwise silently stop every other tenant's schedules,
    which is the worst possible shape for this bug: invisible, and someone
    else's fault.
    """
    from datetime import UTC, datetime

    from app.models.conversations import Conversation, Message
    from app.models.enums import MessageRole, NotificationKind
    from app.repositories.conversations import ConversationRepository, MessageRepository
    from app.repositories.notifications import NotificationRepository
    from app.repositories.presets import PresetRepository
    from app.repositories.schedules import ScheduleRepository
    from app.services.notification_service import notify
    from app.services.rag_service import RAGService
    from app.services.schedule_service import next_run_after

    now = datetime.now(UTC)
    fired = 0

    # The due list is read with no workspace identity because it spans tenants
    # by design; every *action* below re-scopes to the row's own workspace.
    set_identity()
    async with session_scope(session_factory) as session:
        due = await ScheduleRepository(session).due(now)
        pending = [(s.id, s.workspace_id) for s in due]

    for schedule_id, workspace_id in pending:
        set_identity(workspace_id=workspace_id)
        try:
            async with session_scope(session_factory) as session:
                schedules = ScheduleRepository(session)
                schedule = await schedules.get_scoped(schedule_id, workspace_id)
                if schedule is None or not schedule.enabled:
                    continue

                preset = None
                if schedule.preset_id is not None:
                    preset = await PresetRepository(session).get(schedule.preset_id)

                conversations = ConversationRepository(session)
                messages = MessageRepository(session)
                conversation = await conversations.add(
                    Conversation(
                        workspace_id=workspace_id,
                        user_id=schedule.created_by_user_id,
                        title=schedule.name,
                    )
                )
                await conversations.commit()

                rag = RAGService(
                    chunks=ChunkRepository(session),
                    embeddings=embeddings,
                    router=model_router,
                )
                answer, citations, model_used, in_tokens, out_tokens, latency = await rag.answer(
                    workspace_id=workspace_id,
                    question=schedule.prompt,
                    history=[],
                    preferred_model=None,
                    preset_prompt=preset.system_prompt if preset else None,
                )

                await messages.add(
                    Message(
                        conversation_id=conversation.id,
                        workspace_id=workspace_id,
                        role=MessageRole.USER,
                        content=schedule.prompt,
                    )
                )
                await messages.add(
                    Message(
                        conversation_id=conversation.id,
                        workspace_id=workspace_id,
                        role=MessageRole.ASSISTANT,
                        content=answer,
                        citations=[c.model_dump(mode="json") for c in citations],
                        model_used=model_used,
                        input_tokens=in_tokens,
                        output_tokens=out_tokens,
                        latency_ms=latency,
                        preset_id=preset.id if preset else None,
                        preset_version=preset.version if preset else None,
                    )
                )

                # The whole point of a schedule is that it runs while nobody
                # is watching, so without this the answer sits unread in history
                # and the run may as well not have happened.
                await notify(
                    NotificationRepository(session),
                    workspace_id=workspace_id,
                    user_id=schedule.created_by_user_id,
                    kind=NotificationKind.SCHEDULE_RAN,
                    title=f"{schedule.name} is ready",
                    body=answer[:300],
                    conversation_id=conversation.id,
                )

                schedule.last_run_at = now
                schedule.last_error = None
                schedule.next_run_at = next_run_after(schedule.cron, now)
                await schedules.commit()
                fired += 1
                log.info("schedule_ran", schedule=str(schedule_id))

        except Exception as exc:  # noqa: BLE001 - one bad schedule must not stop the rest
            log.warning("schedule_failed", schedule=str(schedule_id), error=str(exc))
            # Record the failure and still move the clock forward. A schedule
            # that keeps its old `next_run_at` after failing would be retried on
            # every tick for ever.
            set_identity(workspace_id=workspace_id)
            async with session_scope(session_factory) as session:
                schedules = ScheduleRepository(session)
                schedule = await schedules.get_scoped(schedule_id, workspace_id)
                if schedule is not None:
                    # Telling someone it broke matters more than telling them it
                    # worked: a silent failure is indistinguishable from a
                    # schedule nobody set up.
                    await notify(
                        NotificationRepository(session),
                        workspace_id=workspace_id,
                        user_id=schedule.created_by_user_id,
                        kind=NotificationKind.SCHEDULE_FAILED,
                        title=f"{schedule.name} did not run",
                        body=str(exc)[:300],
                    )
                    schedule.last_run_at = now
                    schedule.last_error = str(exc)[:500]
                    schedule.next_run_at = next_run_after(schedule.cron, now)
                    await schedules.commit()

    return fired


async def arq_run_due_schedules(ctx: dict[str, Any]) -> int:
    """Arq cron entry point. Resources come from the worker's startup context."""
    return await run_due_schedules(
        session_factory=ctx["session_factory"],
        model_router=ctx["model_router"],
        embeddings=ctx["embeddings"],
    )
