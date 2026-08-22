"""artifacts: what the assistant produced, versioned

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-21 23:49:39.728657
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same predicate every other workspace-scoped table uses. A new table without
# it would be enforced only by the repository layer, losing the database-level
# backstop that makes tenant isolation structural rather than remembered.
POLICY_USING = """
    workspace_id = NULLIF(current_setting('avocado.workspace_id', true), '')::uuid
    OR workspace_id IN (SELECT avocado_visible_workspaces())
"""


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("lineage_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("html", "markdown", "code", "chart", "table", name="artifact_kind"),
            nullable=False,
        ),
        sa.Column("author", sa.Enum("ai", "user", name="artifact_author"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(length=700), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_artifacts_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_artifacts_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_artifacts_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["artifacts.id"],
            name=op.f("fk_artifacts_parent_id_artifacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_artifacts_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
    )
    op.create_index(
        op.f("ix_artifacts_conversation_id"), "artifacts", ["conversation_id"], unique=False
    )
    op.create_index(op.f("ix_artifacts_created_at"), "artifacts", ["created_at"], unique=False)
    op.create_index(op.f("ix_artifacts_lineage_id"), "artifacts", ["lineage_id"], unique=False)
    op.create_index(
        "ix_artifacts_lineage_version", "artifacts", ["lineage_id", "version"], unique=False
    )
    op.create_index(
        "ix_artifacts_workspace_created", "artifacts", ["workspace_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_artifacts_workspace_id"), "artifacts", ["workspace_id"], unique=False)

    op.execute("ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE artifacts FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON artifacts
        USING ({POLICY_USING})
        WITH CHECK ({POLICY_USING})
        """
    )
    # Guarded, so a database that has not created the restricted role still
    # migrates cleanly. An unguarded GRANT fails outright on a fresh checkout.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'avocado_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON artifacts TO avocado_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON artifacts")
    op.drop_index(op.f("ix_artifacts_workspace_id"), table_name="artifacts")
    op.drop_index("ix_artifacts_workspace_created", table_name="artifacts")
    op.drop_index("ix_artifacts_lineage_version", table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_lineage_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_created_at"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_conversation_id"), table_name="artifacts")
    op.drop_table("artifacts")
    # Dropping the table leaves its enum types behind, and the next upgrade
    # then fails on CREATE TYPE. Downgrade has to undo the whole revision.
    op.execute("DROP TYPE IF EXISTS artifact_author")
    op.execute("DROP TYPE IF EXISTS artifact_kind")
