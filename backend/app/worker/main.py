"""Arq worker entry point.

Run with:  arq app.worker.main.WorkerSettings

Builds the same clients the API builds, so a job behaves identically whether it
ran in the worker or (locally) in-process.
"""

from __future__ import annotations

from typing import Any

from app.clients.embeddings.providers import build_embedding_provider
from app.clients.llm.router import ModelRouter, ProviderRegistry
from app.clients.storage.factory import build_storage_client
from app.clients.stt.factory import build_transcription_client
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.rls import install_session_identity
from app.db.session import create_engine, create_session_factory
from app.worker.tasks import arq_ingest_document, arq_transcribe_recording

log = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    engine = create_engine(settings)
    registry = ProviderRegistry(settings)
    install_session_identity()

    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["storage"] = build_storage_client(settings)
    ctx["embeddings"] = build_embedding_provider(settings)
    ctx["registry"] = registry
    ctx["model_router"] = ModelRouter(registry)
    ctx["transcriber"] = build_transcription_client(settings)
    log.info(
        "worker_started",
        env=settings.app_env,
        voice="enabled" if ctx["transcriber"] else "disabled",
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    log.info("worker_stopped")


def _redis_settings():  # type: ignore[no-untyped-def]
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [arq_ingest_document, arq_transcribe_recording]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings()
    # Ingestion is IO- and CPU-mixed; a small pool keeps memory predictable
    # when several large spreadsheets land at once.
    max_jobs = 4
    # Transcription of a long recording is the slowest job here; a one-hour
    # meeting takes materially longer than parsing a PDF.
    job_timeout = 1800
    keep_result = 3600
