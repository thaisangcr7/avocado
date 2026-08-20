"""Row-level security on tenant data tables.

Defence in depth (architecture §13). The repository layer already filters every
query by `workspace_id`; these policies mean a query that *forgot* to still
returns nothing.

Two design notes:

**Only the data tables carry policies**, not the tenancy spine (organizations,
users, teams, memberships, workspaces). Those are small, always reached through
authenticated paths, and — more importantly — the policies below have to read
them to decide visibility. Policing a table that the policy itself consults
invites recursion.

**Visibility is resolved by a SECURITY DEFINER function.** It runs as its
owner, so the membership lookup inside it is not itself subject to RLS. That is
what makes the "workspaces this user belongs to" branch possible without the
policy consulting a policed table.

Enforcement requires the application to connect as a role that is neither a
superuser nor `BYPASSRLS`; see `scripts/create_app_role.sql`. Enabling RLS
while connecting as a superuser is silently a no-op, which is precisely the
trap this migration's docstring exists to flag.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table holding tenant data, keyed by workspace.
WORKSPACE_TABLES = (
    "documents",
    "document_chunks",
    "document_tables",
    "document_classifications",
    "conversations",
    "messages",
    "analysis_runs",
    "voice_recordings",
    "projects",
    "tasks",
)

VISIBLE_WORKSPACES_FN = """
CREATE OR REPLACE FUNCTION avocado_visible_workspaces()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT w.id
    FROM workspaces w
    JOIN teams t ON t.id = w.team_id
    JOIN team_memberships m ON m.team_id = t.id
    WHERE m.user_id = NULLIF(current_setting('avocado.user_id', true), '')::uuid
$$;
"""

# A row is visible when the session is scoped to its workspace (how background
# jobs identify themselves), or when the acting user belongs to it. Both
# settings absent means no rows — unset is nothing, not everything.
POLICY_USING = """
    workspace_id = NULLIF(current_setting('avocado.workspace_id', true), '')::uuid
    OR workspace_id IN (SELECT avocado_visible_workspaces())
"""


def upgrade() -> None:
    op.execute(VISIBLE_WORKSPACES_FN)

    for table in WORKSPACE_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE so the policies still apply if the application ever connects as
        # the table owner. Without it, the owner silently bypasses them.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({POLICY_USING})
            WITH CHECK ({POLICY_USING})
            """
        )

    # project_members has no workspace_id of its own; it inherits its project's.
    op.execute("ALTER TABLE project_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE project_members FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON project_members
        USING (project_id IN (SELECT id FROM projects))
        WITH CHECK (project_id IN (SELECT id FROM projects))
        """
    )

    # Grant the restricted role access if it exists. Guarded, so a development
    # database that has not created the role still migrates cleanly.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'avocado_app') THEN
                GRANT USAGE ON SCHEMA public TO avocado_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO avocado_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO avocado_app;
                GRANT EXECUTE ON FUNCTION avocado_visible_workspaces() TO avocado_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in (*WORKSPACE_TABLES, "project_members"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS avocado_visible_workspaces()")
