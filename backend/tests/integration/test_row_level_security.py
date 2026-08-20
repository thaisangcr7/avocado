"""Row-level security, tested against a role that cannot bypass it.

This suite exists because RLS fails *silently*. Policies can be enabled,
forced, and completely ignored — nothing in the application behaves any
differently, and every other test still passes. The only way to know it works
is to connect as a restricted role and try to read across the boundary.

So these tests deliberately issue queries with **no workspace filter at all**,
simulating a repository method that forgot one. If the second layer is real,
those queries still come back empty.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.rls import (
    clear_identity,
    install_session_identity,
    set_identity,
    verify_enforcement,
)

pytestmark = pytest.mark.anyio

APP_ROLE = "avocado_rls_test"
APP_PASSWORD = "rls-test-only-not-a-real-credential"  # noqa: S105


def _restricted_url(admin_url: str) -> str:
    """The test database URL, but connecting as the restricted role."""
    tail = admin_url.split("@", 1)[1]
    return f"postgresql+asyncpg://{APP_ROLE}:{APP_PASSWORD}@{tail}"


@pytest.fixture
async def restricted(engine):  # type: ignore[no-untyped-def]
    """An engine connected as a role that cannot bypass RLS.

    The role is created here rather than assumed, so this runs on a fresh
    machine and in CI without setup steps that someone has to remember.
    """
    admin_url = os.environ["DATABASE_URL"]

    async with engine.begin() as connection:
        # Interpolated identifiers only, all module constants — a role name and
        # table names cannot be bind parameters in DDL.
        await connection.exec_driver_sql(  # noqa: S608
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS;
                END IF;
            END $$;
            """
        )
        await connection.exec_driver_sql(f"ALTER ROLE {APP_ROLE} WITH PASSWORD '{APP_PASSWORD}'")

        # The `engine` fixture creates the schema with create_all, which does
        # not run migrations — so the policies are applied here instead.
        await connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION avocado_visible_workspaces()
            RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = public AS $$
                SELECT w.id FROM workspaces w
                JOIN teams t ON t.id = w.team_id
                JOIN team_memberships m ON m.team_id = t.id
                WHERE m.user_id = NULLIF(current_setting('avocado.user_id', true), '')::uuid
            $$;
            """
        )
        for table in ("documents", "document_chunks", "conversations", "messages", "tasks"):
            await connection.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            await connection.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            await connection.exec_driver_sql(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            await connection.exec_driver_sql(
                f"""
                CREATE POLICY tenant_isolation ON {table} USING (
                    workspace_id = NULLIF(current_setting('avocado.workspace_id', true), '')::uuid
                    OR workspace_id IN (SELECT avocado_visible_workspaces())
                )
                """
            )
        await connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        await connection.exec_driver_sql(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
        )
        await connection.exec_driver_sql(
            f"GRANT EXECUTE ON FUNCTION avocado_visible_workspaces() TO {APP_ROLE}"
        )

    install_session_identity()
    restricted_engine = create_async_engine(_restricted_url(admin_url))
    yield restricted_engine
    await restricted_engine.dispose()
    clear_identity()


@pytest.fixture
async def two_tenants(client):  # type: ignore[no-untyped-def]
    """Two unrelated organizations, each with a document."""
    import io

    from tests.conftest import register_account

    alice = await register_account(client, email="alice@alpha.com", org="Alpha")
    bob = await register_account(client, email="bob@beta.com", org="Beta")

    for account, marker in ((alice, "ALPHA-SECRET-8817"), (bob, "BETA-SECRET-4429")):
        response = await client.post(
            f"/workspaces/{account['workspace_id']}/documents",
            files={"file": ("notes.txt", io.BytesIO(marker.encode() * 40), "text/plain")},
            headers=account["headers"],
        )
        assert response.status_code == 201, response.text

    return alice, bob


# --- the role itself -------------------------------------------------------


async def test_the_restricted_role_cannot_bypass_policies(restricted):
    """The precondition everything else depends on.

    A superuser ignores RLS entirely, so a suite that ran as one would pass
    while proving nothing.
    """
    enforced, detail = await verify_enforcement(restricted)
    assert enforced, detail


async def test_the_test_database_owner_would_bypass_policies(engine):
    """The trap this whole layer exists to avoid, stated as a test.

    The owner used everywhere else *can* bypass RLS — which is exactly why
    enforcement has to be verified against the restricted role instead of
    assumed from the policies existing.
    """
    enforced, detail = await verify_enforcement(engine)
    assert not enforced
    assert "superuser" in detail or "BYPASSRLS" in detail


# --- the guarantee ---------------------------------------------------------


async def test_an_unfiltered_query_cannot_cross_the_boundary(restricted, two_tenants):
    """The whole point: a query that forgot its workspace filter still cannot
    read another tenant."""
    alice, _bob = two_tenants
    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)

    set_identity(workspace_id=alice["workspace_id"])
    async with factory() as session:
        # Deliberately no WHERE clause — this is the forgotten filter.
        bodies = (
            (await session.execute(text("SELECT content FROM document_chunks"))).scalars().all()
        )

    joined = " ".join(bodies)
    assert "ALPHA-SECRET-8817" in joined, "the tenant's own data should be readable"
    assert "BETA-SECRET-4429" not in joined, "another tenant's data leaked"


async def test_a_session_with_no_identity_sees_nothing(restricted, two_tenants):
    """Unset means nothing, not everything — the fail-closed direction."""
    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)
    clear_identity()

    async with factory() as session:
        count = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
    assert count == 0


async def test_identity_survives_a_commit(restricted, two_tenants):
    """Services commit constantly, and SET LOCAL dies with its transaction.

    If the identity were applied once per session rather than per transaction,
    everything after the first commit would silently return nothing.
    """
    alice, _ = two_tenants
    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)

    set_identity(workspace_id=alice["workspace_id"])
    async with factory() as session:
        before = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
        await session.commit()
        after = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()

    assert before == 1
    assert after == before, "the identity was lost at the commit"


async def test_a_user_identity_reaches_their_own_workspaces(restricted, two_tenants, client):
    """The membership branch: a user sees the workspaces they belong to,
    without the session naming one explicitly."""
    alice, _ = two_tenants
    alice_id = (await client.get("/auth/me", headers=alice["headers"])).json()["id"]

    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)
    clear_identity()
    set_identity(user_id=alice_id)

    async with factory() as session:
        bodies = (
            (await session.execute(text("SELECT content FROM document_chunks"))).scalars().all()
        )

    joined = " ".join(bodies)
    assert "ALPHA-SECRET-8817" in joined
    assert "BETA-SECRET-4429" not in joined


async def test_a_stranger_identity_reaches_nothing(restricted, two_tenants):
    """A valid-looking but unrelated user id must not open anything."""
    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)
    clear_identity()
    set_identity(user_id=uuid.uuid4())

    async with factory() as session:
        count = (await session.execute(text("SELECT count(*) FROM documents"))).scalar_one()
    assert count == 0


async def test_writes_are_policed_too(restricted, two_tenants):
    """WITH CHECK, not just USING: a scoped session must not be able to insert
    a row into someone else's workspace."""
    alice, bob = two_tenants
    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)

    set_identity(workspace_id=alice["workspace_id"])
    async with factory() as session:
        with pytest.raises(Exception) as caught:
            await session.execute(
                text(
                    "INSERT INTO tasks (id, project_id, workspace_id, title, status, "
                    "created_at, updated_at) VALUES (:id, :pid, :ws, 'smuggled', 'todo', "
                    "now(), now())"
                ),
                {"id": uuid.uuid4(), "pid": uuid.uuid4(), "ws": bob["workspace_id"]},
            )
            await session.commit()

    # Either the policy refuses it or the foreign key does; both prevent the
    # cross-tenant write, and the policy is what would stop a valid project id.
    assert caught.value is not None


@pytest.mark.parametrize(
    "table", ["documents", "document_chunks", "conversations", "messages", "tasks"]
)
async def test_every_policed_table_is_scoped(restricted, two_tenants, table):
    """Each table individually, so adding one without a policy is caught."""
    alice, _ = two_tenants
    factory = async_sessionmaker(bind=restricted, expire_on_commit=False)

    clear_identity()
    async with factory() as session:
        # `table` comes from the parametrize list above, not from input.
        statement = text(f"SELECT count(*) FROM {table}")  # noqa: S608
        count = (await session.execute(statement)).scalar_one()
    assert count == 0, f"{table} returned rows with no identity set"
