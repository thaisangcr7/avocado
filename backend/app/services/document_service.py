"""Document upload, listing, retrieval and deletion.

Upload validates before it stores: an oversized or misdeclared file is rejected
without ever reaching object storage. The bytes are read once, hashed, and
checked against prior uploads so re-sending the same file returns the existing
document instead of ingesting a second copy.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable

from app.clients.storage.base import StorageClient, build_storage_key
from app.core.errors import NotFoundError, PayloadTooLargeError, ValidationError
from app.core.logging import get_logger
from app.core.pagination import Page, PageParams
from app.ingestion.detection import detect_document_type
from app.models.documents import Document
from app.models.enums import DocumentStatus
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentResponse,
    DocumentTableResponse,
    DocumentUploadResponse,
)

log = get_logger(__name__)

# Enqueues ingestion for a document. Injected so the service does not care
# whether that means a background task or a queued job.
IngestScheduler = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]


class DocumentService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        tables: DocumentTableRepository,
        storage: StorageClient,
        max_upload_bytes: int,
        schedule_ingest: IngestScheduler,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._tables = tables
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes
        self._schedule_ingest = schedule_ingest

    async def upload(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        data: bytes,
        conversation_id: uuid.UUID | None = None,
    ) -> DocumentUploadResponse:
        if not data:
            raise ValidationError("The uploaded file is empty.")
        if len(data) > self._max_upload_bytes:
            limit_mb = self._max_upload_bytes // (1024 * 1024)
            raise PayloadTooLargeError(f"Files must be {limit_mb}MB or smaller.")

        # Confirms the content matches what the extension and Content-Type
        # claim, before any parser is handed the bytes.
        doc_type = detect_document_type(filename, content_type, data[:64])

        checksum = hashlib.sha256(data).hexdigest()
        existing = await self._documents.find_by_checksum(workspace_id, checksum)
        if existing is not None:
            log.info(
                "document_deduplicated",
                document_id=str(existing.id),
                workspace_id=str(workspace_id),
            )
            return DocumentUploadResponse(
                document=DocumentResponse.model_validate(existing), deduplicated=True
            )

        document_id = uuid.uuid4()
        storage_key = build_storage_key(workspace_id, "documents", str(document_id), filename)
        await self._storage.put(storage_key, data, content_type=content_type)

        document = await self._documents.add(
            Document(
                id=document_id,
                workspace_id=workspace_id,
                uploaded_by=user_id,
                conversation_id=conversation_id,
                filename=filename,
                content_type=content_type,
                doc_type=doc_type,
                size_bytes=len(data),
                storage_key=storage_key,
                checksum_sha256=checksum,
                status=DocumentStatus.PENDING,
                doc_metadata={},
            )
        )
        await self._documents.commit()

        # Committed before scheduling: the worker looks the document up by id,
        # so it must be visible to another transaction first.
        await self._schedule_ingest(document.id, workspace_id)

        log.info(
            "document_uploaded",
            document_id=str(document.id),
            workspace_id=str(workspace_id),
            doc_type=doc_type.value,
            size_bytes=len(data),
        )
        return DocumentUploadResponse(
            document=DocumentResponse.model_validate(document), deduplicated=False
        )

    async def list(self, workspace_id: uuid.UUID, params: PageParams) -> Page[DocumentResponse]:
        page = await self._documents.paginate(workspace_id, params)
        return Page(
            items=[DocumentResponse.model_validate(d) for d in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        )

    async def get(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> DocumentDetailResponse:
        document = await self._documents.get_scoped(document_id, workspace_id)
        if document is None:
            raise NotFoundError("Document not found.")

        tables = await self._tables.list_for_document(document_id, workspace_id)
        return DocumentDetailResponse(
            **DocumentResponse.model_validate(document).model_dump(),
            tables=[DocumentTableResponse.model_validate(t) for t in tables],
        )

    async def delete(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        document = await self._documents.get_scoped(document_id, workspace_id)
        if document is None:
            raise NotFoundError("Document not found.")

        # Stored objects are removed before the rows that point at them: a
        # dangling row is recoverable, an orphaned object is invisible.
        table_keys = await self._tables.delete_for_document(document_id, workspace_id)
        for key in [*table_keys, document.storage_key]:
            await self._storage.delete(key)

        await self._documents.delete(document)
        await self._documents.commit()
        log.info("document_deleted", document_id=str(document_id))

    async def reprocess(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> DocumentResponse:
        document = await self._documents.get_scoped(document_id, workspace_id)
        if document is None:
            raise NotFoundError("Document not found.")

        document.status = DocumentStatus.PENDING
        document.error_message = None
        await self._documents.commit()
        await self._documents.refresh(document)
        await self._schedule_ingest(document_id, workspace_id)
        return DocumentResponse.model_validate(document)
