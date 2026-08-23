"""Shared fixtures.

Integration tests run against a real PostgreSQL with pgvector, not SQLite: the
vector column, the JSONB columns, the enum types and the composite-tuple
cursor comparison have no SQLite equivalent, so testing on SQLite would prove
the wrong thing.

Each test gets a fresh schema. That is slower than transaction rollback but
avoids a whole class of confusing failure where a test's own data is invisible
to the request it just made.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("SANDBOX_BACKEND", "disabled")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# httpx logs every request URL at INFO. That is noise in test output and, worse,
# it puts credentials the application deliberately redacts back into the
# captured logs, which makes leak assertions read as failures.
logging.getLogger("httpx").setLevel(logging.WARNING)

_BASE_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://avocado:avocado@localhost:5434/avocado_test",
)

# Under xdist every worker gets its own database. They share one schema
# otherwise, and one worker truncating tables mid-test in another is the kind
# of failure that only shows up under load and never reproduces alone.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
TEST_DATABASE_URL = f"{_BASE_DATABASE_URL}_{_WORKER}" if _WORKER else _BASE_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def _ensure_database() -> None:
    """Create this worker's database if it is not there yet.

    Connects to the server's default database to do it, because a database
    cannot be created from inside itself. Serial runs use the database that is
    already provisioned and skip this entirely.
    """
    if not _WORKER:
        return

    import psycopg  # noqa: PLC0415 - only needed under xdist

    target = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin = _BASE_DATABASE_URL.replace("+asyncpg", "").rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target,)
        ).fetchone()
        if not exists:
            connection.execute(f'CREATE DATABASE "{target}"')


_ensure_database()

import app.models  # noqa: F401,E402  (registers every table on Base.metadata)
from app.clients.embeddings.providers import HashingEmbeddingProvider  # noqa: E402
from app.clients.llm.router import ModelRouter, ProviderRegistry  # noqa: E402
from app.clients.sandbox.factory import build_limits  # noqa: E402
from app.clients.storage.local import LocalStorageClient  # noqa: E402
from app.clients.tools.registry import McpServers  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.worker.dispatch import (  # noqa: E402
    build_ingest_scheduler,
    build_transcribe_scheduler,
    drain_background_tasks,
)
from tests.fakes import (  # noqa: E402
    FakeLLMProvider,
    FakeSandbox,
    FakeTranscriptionClient,
)


@pytest.fixture(scope="session", autouse=True)
def _configure_logging():
    """Route logs through the stdlib exactly as the application does.

    The `app` fixture deliberately skips lifespan, which is where
    `configure_logging` normally runs. Unconfigured, structlog writes straight
    to stdout and never reaches the logging module — so `caplog` sees nothing
    and any assertion about what is or is not logged silently passes.
    """
    configure_logging("INFO", json_output=False)


@pytest.fixture(scope="session")
def settings():  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def _schema(settings) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Build the schema once for the whole run.

    This used to be per-test, which meant every one of ~300 integration tests
    dropped and recreated every table twice. That was roughly a second each and
    the single largest cost in the suite — minutes of wall clock spent
    rebuilding a structure that never changes between tests.

    What has to be per-test is the *data*, not the structure, and the truncate
    in `engine` does that in milliseconds.

    Synchronous, with its own loop, because pytest-asyncio gives fixtures a
    function-scoped event loop — a session-scoped async fixture cannot have one.
    """

    async def build(drop_only: bool = False) -> None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
        try:
            async with engine.begin() as connection:
                await connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
                await connection.run_sync(Base.metadata.drop_all)
                if not drop_only:
                    await connection.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(build())
    yield
    asyncio.run(build(drop_only=True))


# Emptied before each test, in an order that respects the foreign keys.
_ALL_TABLES = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))


@pytest.fixture
async def engine(_schema) -> AsyncIterator:  # type: ignore[no-untyped-def]
    """An engine against the shared schema, with every table emptied first.

    Truncating is what makes sharing the schema safe: a test still starts from
    nothing, it just does not pay to rebuild the tables to get there. Cleaning
    *before* rather than after also leaves a failed test's rows behind to be
    inspected.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as connection:
        # CASCADE because the tables reference each other; RESTART IDENTITY so
        # no sequence leaks a value from a previous test.
        await connection.exec_driver_sql(
            f"TRUNCATE TABLE {_ALL_TABLES} RESTART IDENTITY CASCADE"  # noqa: S608
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine) -> async_sessionmaker[AsyncSession]:  # type: ignore[no-untyped-def]
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    async with session_factory() as session:
        yield session


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def fake_stt() -> FakeTranscriptionClient:
    return FakeTranscriptionClient()


def apply_test_doubles(  # noqa: PLR0913
    application, *, settings, session_factory, fake_llm, fake_sandbox, fake_stt, storage_path
) -> None:
    """Point the app at test doubles instead of real outbound clients.

    Extracted because `TestClient(app)` as a context manager runs the real
    lifespan, which rebuilds every client from configuration and discards these.
    Anything opening a WebSocket has to re-apply them afterwards.
    """
    registry = ProviderRegistry(settings)
    # The fake is registered through the registry's public seam, so `get()`,
    # `available()` and `find_model()` behave exactly as in production — only
    # the provider behind them is a double.
    registry.register(fake_llm, make_default=True)

    state = application.state
    state.settings = settings
    state.session_factory = session_factory
    state.registry = registry
    state.model_router = ModelRouter(registry)
    state.storage = LocalStorageClient(storage_path)
    state.embeddings = HashingEmbeddingProvider(settings.embedding_dim)
    state.sandbox = fake_sandbox
    state.sandbox_limits = build_limits(settings)
    state.transcriber = fake_stt
    state.mcp_servers = McpServers(settings.mcp_servers)
    state.redis = None
    state.arq_pool = None
    state.schedule_ingest = build_ingest_scheduler(application)
    state.schedule_transcription = build_transcribe_scheduler(application)


@pytest.fixture
async def app(  # type: ignore[no-untyped-def]
    settings, session_factory, fake_llm, fake_sandbox, fake_stt, tmp_path
):
    """The real application, with only its outbound clients replaced.

    Routers, dependencies, middleware, services and repositories are all the
    production ones — swapping those out would leave the wiring untested,
    which is most of what an integration test is for.
    """
    application = create_app()
    apply_test_doubles(
        application,
        settings=settings,
        session_factory=session_factory,
        fake_llm=fake_llm,
        fake_sandbox=fake_sandbox,
        fake_stt=fake_stt,
        storage_path=str(tmp_path / "storage"),
    )

    yield application

    # Ingestion runs in-process here. Draining before the `engine` fixture
    # drops the schema keeps a still-running job from deadlocking against the
    # teardown DDL — the same reason the app drains on shutdown.
    await drain_background_tasks(seconds=30)


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    # ASGITransport drives the app in-process — no socket, no lifespan. State
    # is set by the `app` fixture instead, which is why lifespan is skipped.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1"
    ) as http_client:
        yield http_client


async def register_account(
    client: AsyncClient, *, email: str | None = None, org: str = "Acme"
) -> dict:
    """Create an account and return its tokens plus its default workspace."""
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "full_name": "Test User",
            "organization_name": org,
        },
    )
    assert response.status_code == 201, response.text
    tokens = response.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    workspaces = await client.get("/workspaces", headers=headers)
    assert workspaces.status_code == 200, workspaces.text
    return {
        "email": email,
        "headers": headers,
        "tokens": tokens,
        "workspace_id": workspaces.json()[0]["id"],
    }


@pytest.fixture
async def account(client) -> dict:  # type: ignore[no-untyped-def]
    return await register_account(client)


async def quiesce_llm(fake_llm, *, settle: float = 0.05, attempts: int = 60) -> None:
    """Wait until background work has stopped calling the fake provider.

    Ingestion classifies a document *after* marking it ready, so a test that
    seeds a document and then assigns `fake_llm.responses` can have that late
    classification consume the first response it meant for itself. Waiting for
    readiness is not enough; the call count settling is what says the
    background pass is actually done.
    """
    seen = -1
    stable = 0
    for _ in range(attempts):
        count = len(fake_llm.calls)
        if count == seen:
            stable += 1
            if stable >= 2:
                return
        else:
            seen = count
            stable = 0
        await asyncio.sleep(settle)
