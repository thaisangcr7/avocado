"""FastAPI application factory and lifespan.

Everything expensive — the database engine, provider clients, the storage
client, the queue pool — is built once at startup and hung off `app.state`, so
a request pays for none of it. Nothing here reads configuration at request
time either; that all happened at boot, where a bad value fails loudly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    register_exception_handlers,
)
from app.api.v1.router import api_router
from app.clients.embeddings.providers import build_embedding_provider
from app.clients.llm.router import ModelRouter, ProviderRegistry
from app.clients.sandbox.factory import build_limits, build_sandbox
from app.clients.storage.factory import build_storage_client
from app.clients.stt.factory import build_transcription_client
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_session_factory
from app.worker.dispatch import (
    build_ingest_scheduler,
    build_transcribe_scheduler,
    drain_background_tasks,
)

log = get_logger(__name__)

DESCRIPTION = """
Avocado ingests a team's documents, spreadsheets and images and makes them
answerable — with citations for what it retrieved, and executed code for what
it computed.

* **Ingest** PDFs, Word files, spreadsheets, CSVs, images and text.
* **Ask** questions and get answers grounded in those documents, cited.
* **Analyse** spreadsheets with real computation: the model writes pandas, the
  code runs in an isolated sandbox, and you get both the answer and the program
  that produced it.
"""


async def _probe_ollama(registry: ProviderRegistry) -> None:
    """Discover which local models Ollama actually has.

    Unlike the hosted providers, Ollama needs no credential, so configuration
    cannot tell us whether it is running or what has been pulled — its model
    list is empty until something asks. Without this probe its models never
    appear in the catalogue, which is the whole point of wiring it in.
    """
    try:
        provider = registry.get("ollama")
    except Exception:
        return

    refresh = getattr(provider, "refresh_models", None)
    if refresh is None:
        return

    try:
        models = await refresh()
    except Exception:
        log.info("ollama_unreachable")
        registry.mark_unavailable("ollama")
        return

    if models:
        log.info("ollama_models_discovered", count=len(models))
    else:
        # Reachable but nothing pulled — offering it would produce a picker
        # entry that cannot answer.
        registry.mark_unavailable("ollama")


async def _connect_redis(settings: Settings):  # type: ignore[no-untyped-def]
    """Connect to Redis, or return None.

    Redis backs rate limiting and the job queue. Both have working fallbacks,
    so an unreachable Redis degrades the app rather than stopping it — but it
    is logged as a warning, not swallowed.
    """
    try:
        from redis.asyncio import from_url

        client = from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        return client
    except Exception:
        log.warning("redis_unavailable", url_scheme=settings.redis_url.split("://")[0])
        return None


async def _connect_queue(settings: Settings):  # type: ignore[no-untyped-def]
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        return await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception:
        log.warning("queue_unavailable")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings: Settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    engine = create_engine(settings)
    registry = ProviderRegistry(settings)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.registry = registry
    app.state.model_router = ModelRouter(registry)
    app.state.storage = build_storage_client(settings)
    app.state.embeddings = build_embedding_provider(settings)
    app.state.sandbox = build_sandbox(settings)
    app.state.sandbox_limits = build_limits(settings)
    app.state.transcriber = build_transcription_client(settings)
    await _probe_ollama(registry)
    app.state.redis = await _connect_redis(settings)
    app.state.arq_pool = await _connect_queue(settings)
    app.state.schedule_ingest = build_ingest_scheduler(app)
    app.state.schedule_transcription = build_transcribe_scheduler(app)

    log.info(
        "app_started",
        env=settings.app_env,
        storage=app.state.storage.name,
        embeddings=app.state.embeddings.name,
        sandbox=settings.sandbox_backend,
        voice=app.state.transcriber.name if app.state.transcriber else "disabled",
        providers=[p.name for p in registry.available()],
    )

    try:
        yield
    finally:
        # Let in-flight in-process ingestion finish before the engine goes
        # away, or its transactions die mid-write.
        await drain_background_tasks()
        await engine.dispose()
        if app.state.redis is not None:
            await app.state.redis.aclose()
        if app.state.arq_pool is not None:
            await app.state.arq_pool.aclose()
        log.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Avocado API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs are useful in development and an information leak in
        # production, so they are off there.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Middleware runs bottom-up: request context is added first so the rate
    # limiter's own rejection is already logged with a request id.
    # Reads its Redis client from app state per request — see the middleware.
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limit=settings.rate_limit_requests,
            org_limit=settings.rate_limit_org_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "Avocado API",
            "version": "0.1.0",
            "docs": "/docs" if not settings.is_production else "disabled",
            "health": f"{settings.api_v1_prefix}/ready",
        }

    return app


app = create_app()
