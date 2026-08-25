"""workspace grounding mode and message grounded flag

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-24 21:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "require_grounding",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("messages", sa.Column("grounded", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "grounded")
    op.drop_column("workspaces", "require_grounding")
