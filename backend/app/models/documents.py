"""Documents, their retrievable chunks, and their structured tabular form."""

from __future__ import annotations

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentStatus, DocumentType

# The vector column needs a fixed width at DDL time. Every embedding provider
# is configured to emit exactly this many dimensions (see clients/embeddings).
EMBEDDING_DIM = get_settings().embedding_dim


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_workspace_status", "workspace_id", "status"),
        Index("ix_documents_workspace_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(700), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Parser-produced facts that don't deserve their own column: sheet names,
    # image dimensions, detected language, OCR-vs-vision provenance.
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tables: Mapped[list[DocumentTable]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_workspace_doc", "workspace_id", "document_id"),
        Index(
            "ix_document_chunks_ws_doc_idx",
            "workspace_id",
            "document_id",
            "chunk_index",
        ),
        # HNSW rather than IVFFlat: IVFFlat needs representative data at build
        # time to choose useful centroids, so building it on an empty table
        # quietly costs recall. HNSW is correct from the first row.
        #
        # The operator class must match the distance function the retrieval
        # query uses (cosine, see ChunkRepository.search) or the planner will
        # not use this index at all.
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )

    # Denormalised from `documents` on purpose: it lets every retrieval query
    # filter by tenant without joining, so the isolation predicate is on the
    # table actually being scanned.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    # Where this chunk came from, for citation rendering: page number, sheet
    # name, row range, section heading.
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class DocumentTable(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A spreadsheet sheet kept in structured form for the analysis engine.

    Spreadsheets are embedded for retrieval *and* preserved as tables. The
    embedded text answers "which document mentions Q3 revenue"; this row is
    what pandas actually runs against to compute it.
    """

    __tablename__ = "document_tables"
    __table_args__ = (Index("ix_document_tables_workspace_doc", "workspace_id", "document_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Canonical CSV in object storage — one normalised format for the sandbox
    # to load regardless of whether the upload was .xlsx or .csv.
    storage_key: Mapped[str] = mapped_column(String(700), nullable=False)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # [{name, dtype, null_count, sample_values: [...]}] — this is the schema
    # summary handed to the model so it can write code without seeing the data.
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    document: Mapped[Document] = relationship(back_populates="tables")
