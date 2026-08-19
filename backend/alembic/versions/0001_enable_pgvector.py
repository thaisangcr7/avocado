"""Enable the pgvector extension.

Kept as its own migration and ordered first: the vector column type in the next
migration cannot be created until the extension exists, and separating it makes
the dependency explicit rather than incidental.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Deliberately not dropped: other schemas in the same database may rely on
    # it, and dropping an extension cascades to columns using its types.
    pass
