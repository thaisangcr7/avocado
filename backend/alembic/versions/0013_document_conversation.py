"""documents: remember which conversation a file arrived in

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-22 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_documents_conversation_id"), "documents", ["conversation_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_documents_conversation_id_conversations"),
        "documents",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_documents_conversation_id_conversations"), "documents", type_="foreignkey"
    )
    op.drop_index(op.f("ix_documents_conversation_id"), table_name="documents")
    op.drop_column("documents", "conversation_id")
