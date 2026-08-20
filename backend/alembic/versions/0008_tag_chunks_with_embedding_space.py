"""tag chunks with the embedding space that produced them

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-20 15:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.config import get_settings

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every chunk that exists when this runs was embedded by the hashing provider:
# it is the default, and the config refuses to boot any other provider without
# its API key. Backfilling the real value rather than leaving NULL keeps those
# rows searchable instead of stranding them the moment retrieval starts
# filtering on the space. The width comes from settings for the same reason the
# vector column itself does — it is deployment-configurable.
_LEGACY_SIGNATURE = f"hash:bagofwords:{get_settings().embedding_dim}"


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE document_chunks SET embedding_model = :signature "
            "WHERE embedding IS NOT NULL AND embedding_model IS NULL"
        ).bindparams(signature=_LEGACY_SIGNATURE)
    )
    op.create_index(
        "ix_document_chunks_embedding_model",
        "document_chunks",
        ["embedding_model"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_model", table_name="document_chunks")
    op.drop_column("document_chunks", "embedding_model")
