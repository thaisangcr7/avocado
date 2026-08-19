"""Deciding how a background job actually runs.

Two paths, same job function:

* **Queued (Arq/Redis)** — the deployed path. Ingestion runs in a separate
  worker process, so a large PDF cannot occupy an API worker, and a job
  survives an API restart.
* **In-process** — the fallback when no queue is reachable. Keeps
  `docker-compose up` and the test suite working without a worker running. It
  is genuinely weaker: a job dies with the process. That is an acceptable
  local-development trade and never the production path.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI

from app.core.logging import get_logger
from app.worker.tasks import ingest_document, transcribe_recording

log = get_logger(__name__)

INGEST_JOB = "arq_ingest_document"
TRANSCRIBE_JOB = "arq_transcribe_recording"

IngestScheduler = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]
TranscribeScheduler = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]

# Holds strong references to in-flight fallback tasks. Without this the event
# loop only keeps a weak reference and a job can be garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()

# How long shutdown waits for in-flight in-process jobs before giving up.
DRAIN_TIMEOUT_SECONDS = 30


def build_ingest_scheduler(app: FastAPI) -> IngestScheduler:
    async def schedule(document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        pool = getattr(app.state, "arq_pool", None)
        if pool is not None:
            try:
                await pool.enqueue_job(INGEST_JOB, str(document_id), str(workspace_id))
                log.info("ingest_enqueued", document_id=str(document_id))
                return
            except Exception:
                # Losing the queue must not lose the document; fall through to
                # the in-process path and say so loudly.
                log.warning("ingest_enqueue_failed", exc_info=True)

        log.info("ingest_inprocess", document_id=str(document_id))
        task = asyncio.create_task(
            ingest_document(
                session_factory=app.state.session_factory,
                storage=app.state.storage,
                embeddings=app.state.embeddings,
                router=app.state.model_router,
                document_id=document_id,
                workspace_id=workspace_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return schedule


def build_transcribe_scheduler(app: FastAPI) -> TranscribeScheduler:
    """Same two-path dispatch as ingestion: queue when there is one, in-process
    otherwise so local development works without a worker."""

    async def schedule(recording_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        pool = getattr(app.state, "arq_pool", None)
        if pool is not None:
            try:
                await pool.enqueue_job(TRANSCRIBE_JOB, str(recording_id), str(workspace_id))
                log.info("transcription_enqueued", recording_id=str(recording_id))
                return
            except Exception:
                log.warning("transcription_enqueue_failed", exc_info=True)

        log.info("transcription_inprocess", recording_id=str(recording_id))
        task = asyncio.create_task(
            transcribe_recording(
                session_factory=app.state.session_factory,
                storage=app.state.storage,
                embeddings=app.state.embeddings,
                router=app.state.model_router,
                transcriber=app.state.transcriber,
                max_audio_bytes=app.state.settings.max_audio_bytes,
                recording_id=recording_id,
                workspace_id=workspace_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return schedule


async def drain_background_tasks(seconds: float = DRAIN_TIMEOUT_SECONDS) -> None:
    """Wait for in-process jobs to finish before the process goes away.

    Without this a restart kills ingestion mid-transaction: the document is
    left in `processing` forever, and the half-written chunks block the schema
    locks that a deploy or a test teardown needs. Jobs still running after the
    timeout are cancelled rather than held onto indefinitely.
    """
    pending = {task for task in _background_tasks if not task.done()}
    if not pending:
        return

    log.info("draining_background_tasks", count=len(pending))
    done, still_running = await asyncio.wait(pending, timeout=seconds)
    for task in still_running:
        log.warning("background_task_cancelled_at_shutdown")
        task.cancel()
    if still_running:
        await asyncio.gather(*still_running, return_exceptions=True)

    # Surface failures that nothing else would have reported.
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            log.error("background_task_failed", error=str(task.exception()))
