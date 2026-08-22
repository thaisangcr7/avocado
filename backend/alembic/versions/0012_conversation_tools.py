"""conversation_tools: explicit per-thread tool choices

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-22 01:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_tools",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("tool_slug", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
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
            name=op.f("fk_conversation_tools_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_tools")),
        sa.UniqueConstraint("conversation_id", "tool_slug", name="uq_conversation_tools_pair"),
    )
    op.create_index(
        op.f("ix_conversation_tools_conversation_id"),
        "conversation_tools",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_tools_created_at"), "conversation_tools", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_conversation_tools_tool_slug"), "conversation_tools", ["tool_slug"], unique=False
    )

    # No workspace_id of its own; it inherits the conversation's, the same way
    # project_members inherits its project's.
    op.execute("ALTER TABLE conversation_tools ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversation_tools FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON conversation_tools
        USING (conversation_id IN (SELECT id FROM conversations))
        WITH CHECK (conversation_id IN (SELECT id FROM conversations))
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'avocado_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON conversation_tools TO avocado_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON conversation_tools")
    op.drop_index(op.f("ix_conversation_tools_tool_slug"), table_name="conversation_tools")
    op.drop_index(op.f("ix_conversation_tools_created_at"), table_name="conversation_tools")
    op.drop_index(op.f("ix_conversation_tools_conversation_id"), table_name="conversation_tools")
    op.drop_table("conversation_tools")
