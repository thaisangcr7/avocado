"""The ingestion pipeline: stored bytes -> retrievable chunks + analysable tables.

    parse (type-specific)  ->  chunk  ->  embed  ->  persist

Parsing is synchronous and CPU-bound (pypdf, openpyxl, pandas), so it runs in a
worker thread rather than blocking the event loop. Images take a different
route entirely: there is no text to extract, so Claude's vision input produces
a description that is then chunked and embedded like any other text.

Reprocessing is idempotent — existing chunks and tables for a document are
removed before new ones are written, so a re-run never doubles a document's
presence in retrieval.
"""

from __future__ import annotations

import asyncio
import base64
import uuid

from app.clients.embeddings.base import EmbeddingProvider
from app.clients.llm.base import ChatMessage, ImagePart
from app.clients.llm.router import ModelRouter, TaskType
from app.clients.storage.base import StorageClient, build_storage_key
from app.core.errors import ProviderError, ValidationError
from app.core.logging import get_logger
from app.ingestion.chunking import chunk_blocks, estimate_tokens
from app.ingestion.detection import image_media_type
from app.ingestion.parsers import SYNC_PARSERS
from app.ingestion.rasterize import render_pdf_pages
from app.ingestion.types import ParsedDocument, TextBlock
from app.models.documents import Document, DocumentChunk, DocumentTable
from app.models.enums import DocumentStatus, DocumentType
from app.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    DocumentTableRepository,
)

log = get_logger(__name__)

VISION_PROMPT = (
    "Describe this image so it can be found later by someone searching a "
    "knowledge base and answered from without seeing the image.\n\n"
    "Cover, in prose:\n"
    "- What kind of image it is (chart, screenshot, diagram, photo, scanned page)\n"
    "- Every piece of text visible in it, transcribed accurately\n"
    "- For charts and tables: the axes, series, categories, and the actual "
    "values or clear approximations\n"
    "- What the image shows or claims overall\n\n"
    "Write only the description. Do not add commentary about the task."
)

# Vision descriptions are prose, not documents — a few thousand tokens is
# ample and caps the cost of a large image batch.
VISION_MAX_TOKENS = 2048

SCANNED_PAGE_PROMPT = (
    "Transcribe all text in this scanned page, preserving reading order, "
    "headings, and list structure. Reproduce the words exactly — do not "
    "summarise, correct, or explain. If the page also contains a table or "
    "chart, transcribe its contents as text. If the page is blank, reply with "
    "nothing at all."
)


class IngestionService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        tables: DocumentTableRepository,
        storage: StorageClient,
        embeddings: EmbeddingProvider,
        router: ModelRouter,
        ocr_enabled: bool = True,
        ocr_max_pages: int = 20,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._tables = tables
        self._storage = storage
        self._embeddings = embeddings
        self._router = router
        self._ocr_enabled = ocr_enabled
        self._ocr_max_pages = ocr_max_pages

    async def process(self, document: Document) -> None:
        """Run the full pipeline for one document.

        Failure is recorded on the document rather than raised: ingestion runs
        in the background, and a user needs to see *why* a file failed in the
        document list, not lose it to a worker traceback.
        """
        workspace_id = document.workspace_id
        try:
            await self._documents.set_status(document.id, workspace_id, DocumentStatus.PROCESSING)
            await self._documents.commit()

            data = await self._storage.get(document.storage_key)
            parsed = await self._parse(document, data)

            if not parsed.text_blocks and not parsed.tables:
                raise ValidationError("No readable content was found in this file.")

            # Idempotence: clear prior output before writing new output.
            await self._chunks.delete_for_document(document.id, workspace_id)
            stale_keys = await self._tables.delete_for_document(document.id, workspace_id)
            for key in stale_keys:
                await self._storage.delete(key)

            await self._persist_tables(document, parsed)
            chunk_count = await self._persist_chunks(document, parsed)

            document.chunk_count = chunk_count
            document.page_count = parsed.page_count
            document.doc_metadata = {**document.doc_metadata, **parsed.metadata}
            document.status = DocumentStatus.READY
            document.error_message = None
            await self._documents.commit()

            log.info(
                "document_ingested",
                document_id=str(document.id),
                workspace_id=str(workspace_id),
                chunks=chunk_count,
                tables=len(parsed.tables),
            )

        except Exception as exc:
            # A user-facing message for the errors we raise deliberately; a
            # generic one for anything else, so an internal detail never
            # surfaces in the document list.
            detail = (
                str(exc)
                if isinstance(exc, ValidationError | ProviderError)
                else "Processing failed. The file may be corrupt or unsupported."
            )
            log.exception(
                "document_ingest_failed",
                document_id=str(document.id),
                workspace_id=str(workspace_id),
            )
            await self._documents.set_status(
                document.id, workspace_id, DocumentStatus.FAILED, error_message=detail
            )
            await self._documents.commit()

    async def _parse(self, document: Document, data: bytes) -> ParsedDocument:
        if document.doc_type is DocumentType.IMAGE:
            return await self._parse_image(document, data)

        parser = SYNC_PARSERS.get(document.doc_type)
        if parser is None:
            raise ValidationError(f"No parser is available for '{document.doc_type.value}' files.")

        parsed: ParsedDocument = await asyncio.to_thread(parser, data, document.filename)

        # A PDF whose pages yield no text is a scan: a stack of photographs.
        # Without this it would ingest as an empty document and be invisible to
        # retrieval, which reads to the user as the file simply not working.
        if document.doc_type is DocumentType.PDF and parsed.metadata.get("likely_scanned"):
            if not self._ocr_enabled:
                parsed.metadata["ocr_fallback"] = "disabled"
                raise ValidationError(
                    "This PDF appears to be scanned and contains no extractable "
                    "text. Text recovery is disabled on this deployment."
                )
            return await self._read_scanned_pdf(document, data, parsed)

        return parsed

    async def _read_scanned_pdf(
        self, document: Document, data: bytes, parsed: ParsedDocument
    ) -> ParsedDocument:
        """Recover a scanned PDF by reading its pages as images."""
        pages = await asyncio.to_thread(render_pdf_pages, data, max_pages=self._ocr_max_pages)
        if not pages:
            raise ValidationError("This PDF appears to be scanned and could not be read.")

        provider, spec = self._router.resolve(task=TaskType.VISION_EXTRACTION)
        if not spec.supports_vision:
            raise ProviderError(f"Model '{spec.id}' cannot read scanned pages.")

        blocks: list[TextBlock] = []
        for page in pages:
            result = await provider.generate(
                messages=[
                    ChatMessage(
                        role="user",
                        content=SCANNED_PAGE_PROMPT,
                        images=[
                            ImagePart(
                                media_type="image/png",
                                data_b64=base64.standard_b64encode(page.png_bytes).decode(),
                            )
                        ],
                    )
                ],
                model=spec.id,
                max_tokens=VISION_MAX_TOKENS,
            )
            text = result.text.strip()
            if text:
                blocks.append(
                    TextBlock(
                        content=text,
                        metadata={"page": page.page_number, "source": "scanned"},
                    )
                )

        if not blocks:
            raise ValidationError("No text could be read from this scanned PDF.")

        total_pages = parsed.page_count or len(pages)
        skipped = max(0, total_pages - len(pages))
        log.info(
            "scanned_pdf_recovered",
            document_id=str(document.id),
            pages_read=len(pages),
            pages_skipped=skipped,
        )
        return ParsedDocument(
            text_blocks=blocks,
            tables=parsed.tables,
            page_count=total_pages,
            metadata={
                **parsed.metadata,
                "parser": "vision-ocr",
                "ocr_fallback": "used",
                "ocr_pages_read": len(pages),
                # Recorded so a truncated read is visible rather than silent.
                "ocr_pages_skipped": skipped,
                "vision_model": spec.id,
            },
        )

    async def _parse_image(self, document: Document, data: bytes) -> ParsedDocument:
        """Describe an image with the vision model so it becomes searchable."""
        media_type = image_media_type(document.filename)
        provider, spec = self._router.resolve(task=TaskType.VISION_EXTRACTION)
        if not spec.supports_vision:
            raise ProviderError(f"Model '{spec.id}' cannot read images.")

        result = await provider.generate(
            messages=[
                ChatMessage(
                    role="user",
                    content=VISION_PROMPT,
                    images=[
                        ImagePart(
                            media_type=media_type,
                            data_b64=base64.standard_b64encode(data).decode(),
                        )
                    ],
                )
            ],
            model=spec.id,
            max_tokens=VISION_MAX_TOKENS,
        )

        description = result.text.strip()
        if not description:
            raise ProviderError("The vision model returned an empty description.")

        return ParsedDocument(
            text_blocks=[
                TextBlock(
                    content=description,
                    metadata={"source": "vision", "model": result.model},
                )
            ],
            metadata={
                "parser": "claude-vision",
                "vision_model": result.model,
                "media_type": media_type,
            },
        )

    async def _persist_tables(self, document: Document, parsed: ParsedDocument) -> None:
        if not parsed.tables:
            return

        rows: list[DocumentTable] = []
        for table in parsed.tables:
            key = build_storage_key(
                document.workspace_id,
                "tables",
                str(document.id),
                f"{table.sheet_index}_{table.name}.csv",
            )
            await self._storage.put(key, table.csv_bytes, content_type="text/csv")
            rows.append(
                DocumentTable(
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    name=table.name,
                    sheet_index=table.sheet_index,
                    storage_key=key,
                    row_count=table.row_count,
                    column_count=len(table.columns),
                    columns=[c.to_dict() for c in table.columns],
                )
            )
        await self._tables.bulk_add(rows)

    async def _persist_chunks(self, document: Document, parsed: ParsedDocument) -> int:
        pieces = chunk_blocks(parsed.text_blocks)
        if not pieces:
            return 0

        vectors = await self._embeddings.embed([p.content for p in pieces], kind="document")
        if len(vectors) != len(pieces):
            raise ProviderError("The embedding provider returned an unexpected count.")

        await self._chunks.bulk_add(
            [
                DocumentChunk(
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    chunk_index=index,
                    content=piece.content,
                    token_count=estimate_tokens(piece.content),
                    embedding=vector,
                    embedding_model=self._embeddings.signature,
                    chunk_metadata=piece.metadata,
                )
                for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))
            ]
        )
        return len(pieces)

    async def reprocess(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        document = await self._documents.get_scoped(document_id, workspace_id)
        if document is None:
            raise ValidationError("Document not found.")
        await self.process(document)
