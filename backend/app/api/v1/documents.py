"""Document routes.

Workspace-nested routes authorise via `WorkspaceContextDep`. The two flat
routes (`/documents/{id}`) authorise inside the repository query itself, so a
document id from the client is never acted on before membership is proven.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status

from app.api.deps import (
    ChunksDep,
    CurrentUserDep,
    DocumentsDep,
    SettingsDep,
    StorageDep,
    TablesDep,
    WorkspaceContextDep,
)
from app.core.errors import NotFoundError, PayloadTooLargeError
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageParams
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService

router = APIRouter(tags=["documents"])


def get_document_service(
    request: Request,
    documents: DocumentsDep,
    chunks: ChunksDep,
    tables: TablesDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> DocumentService:
    return DocumentService(
        documents=documents,
        chunks=chunks,
        tables=tables,
        storage=storage,
        max_upload_bytes=settings.max_upload_bytes,
        schedule_ingest=request.app.state.schedule_ingest,
    )


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    context: WorkspaceContextDep,
    service: DocumentServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    conversation_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentUploadResponse:
    """Upload a PDF, Word file, spreadsheet, CSV, image or text file.

    Ingestion runs in the background; poll the document's `status` until it
    reaches `ready` (or `failed`, which carries the reason).
    """
    # Read in bounded chunks and stop the moment the limit is passed, rather
    # than buffering an arbitrarily large body first and checking after.
    limit = settings.max_upload_bytes
    buffer = bytearray()
    total = 0
    while chunk := await file.read(4 * 1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError(f"Files must be {limit // (1024 * 1024)}MB or smaller.")
        buffer.extend(chunk)

    return await service.upload(
        workspace_id=context.id,
        user_id=context.user.id,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=bytes(buffer),
        conversation_id=conversation_id,
    )


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=PaginatedResponse[DocumentResponse],
)
async def list_documents(
    context: WorkspaceContextDep,
    service: DocumentServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> PaginatedResponse[DocumentResponse]:
    page = await service.list(context.id, PageParams(limit=limit, cursor=cursor))
    return PaginatedResponse(items=page.items, next_cursor=page.next_cursor, has_more=page.has_more)


async def _resolve_document_workspace(
    document_id: uuid.UUID, user: CurrentUserDep, documents: DocumentsDep
) -> uuid.UUID:
    """Authorise a flat document route and return its workspace id.

    The repository join is the access check — a document the caller cannot
    reach is simply not returned, and reads as 404 rather than confirming the
    id exists.
    """
    document = await documents.get_for_user(document_id, user.id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document.workspace_id


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: uuid.UUID,
    workspace_id: Annotated[uuid.UUID, Depends(_resolve_document_workspace)],
    service: DocumentServiceDep,
) -> DocumentDetailResponse:
    return await service.get(document_id, workspace_id)


@router.delete("/documents/{document_id}", response_model=MessageResponse)
async def delete_document(
    document_id: uuid.UUID,
    workspace_id: Annotated[uuid.UUID, Depends(_resolve_document_workspace)],
    service: DocumentServiceDep,
) -> MessageResponse:
    await service.delete(document_id, workspace_id)
    return MessageResponse(message="Document deleted.")


@router.post("/documents/{document_id}/reprocess", response_model=DocumentResponse)
async def reprocess_document(
    document_id: uuid.UUID,
    workspace_id: Annotated[uuid.UUID, Depends(_resolve_document_workspace)],
    service: DocumentServiceDep,
) -> DocumentResponse:
    """Re-run ingestion — after a transient failure, or a parser improvement."""
    return await service.reprocess(document_id, workspace_id)
