"""Add the HNSW index for chunk similarity search.

HNSW rather than IVFFlat: IVFFlat has to be built against representative data
to pick useful centroids, so building it on an empty table produces a bad index
that silently degrades recall. HNSW builds incrementally and is correct from
the first row, which matters here because the index ships before any corpus
exists.

The index covers cosine distance because that is the operator the retrieval
query uses (`ChunkRepository.search`); an index built for a different operator
class would simply not be used.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    # Retrieval always filters by workspace before ranking, so this composite
    # index is what keeps the pre-filter cheap on a large corpus.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_ws_doc_idx
        ON document_chunks (workspace_id, document_id, chunk_index)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_ws_doc_idx")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
