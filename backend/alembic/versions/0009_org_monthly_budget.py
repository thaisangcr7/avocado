"""give an organization a monthly spend ceiling

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-20 15:51:05.427673
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable with no default: an organization that never set a budget has no
    # ceiling, rather than inheriting one it did not choose.
    op.add_column("organizations", sa.Column("monthly_budget_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "monthly_budget_usd")
