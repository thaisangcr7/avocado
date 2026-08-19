"""Document resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import DocumentStatus, DocumentType
from app.schemas.common import ApiModel


class DocumentResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    filename: str
    content_type: str
    doc_type: DocumentType
    size_bytes: int
    status: DocumentStatus
    error_message: str | None
    page_count: int | None
    chunk_count: int
    doc_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentColumnResponse(BaseModel):
    name: str
    dtype: str
    null_count: int = 0
    sample_values: list[Any] = []


class DocumentTableResponse(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    name: str
    sheet_index: int
    row_count: int
    column_count: int
    columns: list[dict[str, Any]]


class DocumentDetailResponse(DocumentResponse):
    """A document plus its analysable tables.

    `tables` being non-empty is what tells the UI to offer the analysis view
    for this document.
    """

    tables: list[DocumentTableResponse] = []


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    # True when an identical file already existed and was returned instead of
    # being ingested a second time.
    deduplicated: bool = False
