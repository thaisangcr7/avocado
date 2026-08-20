"""The org knowledge layer: classifying documents into what they *are*.

Architecture §5 calls this the most differentiated part of the vision and also
the part most worth deferring — it only pays off once ingestion is solid, which
it now is. A tagging pass turns a pile of uploaded files into a queryable map:
which documents are policies, which describe processes, what subjects they
cover, and when they took effect.

Classification runs on the document's own opening text, not the whole file. A
policy announces what it is in its first page; sending fifty pages to decide
"is this a policy?" costs a great deal for no additional signal.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError

from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.core.errors import NotFoundError, ProviderError
from app.core.logging import get_logger
from app.models.documents import Document
from app.models.enums import DocumentKind
from app.models.knowledge import DocumentClassification
from app.repositories.documents import ChunkRepository, DocumentRepository
from app.repositories.knowledge import ClassificationRepository
from app.schemas.projects import (
    ClassificationResponse,
    ClassifiedDocument,
    KnowledgeMapResponse,
)

log = get_logger(__name__)

# How much of a document the classifier reads. Roughly the first couple of
# pages, which is where a document says what it is.
CLASSIFY_CHARS = 6000

CLASSIFY_PROMPT = """Classify this document by what it is to the team that \
uploaded it.

kind:
- "policy" — states rules people must follow (leave, expenses, security, conduct)
- "process" — describes how something is done, step by step (onboarding, \
deployment, incident response)
- "project" — concerns a specific initiative: plans, specs, status, retrospectives
- "reference" — data, research, background, or material kept for lookup
- "other" — none of the above

Also give:
- title: the document's own title if it has one, otherwise a short descriptive one
- summary: two sentences on what it covers and who it affects
- topics: up to five short lowercase subject tags, e.g. "expenses", "onboarding"
- effective_date: the date it takes effect as YYYY-MM-DD, or null if not stated
- confidence: 0 to 1, how sure you are of the kind

Judge only from the text. Do not infer an effective date from a date that is \
merely mentioned."""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [k.value for k in DocumentKind],
        },
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "effective_date": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "title", "summary", "topics", "effective_date", "confidence"],
    "additionalProperties": False,
}


class KnowledgeService:
    def __init__(
        self,
        *,
        classifications: ClassificationRepository,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        router: ModelRouter,
    ) -> None:
        self._classifications = classifications
        self._documents = documents
        self._chunks = chunks
        self._router = router

    async def classify_document(
        self,
        *,
        document_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID | None = None,
        preferred_model: str | None = None,
    ) -> ClassificationResponse | None:
        """Tag one document. Returns None when it could not be classified.

        Returns rather than raises: this runs as part of ingestion, and a
        document that could not be classified is still a perfectly good
        document. Failing the whole ingest over a missing tag would be the
        wrong trade.
        """
        document = await self._documents.get_scoped(document_id, workspace_id)
        if document is None:
            raise NotFoundError("Document not found.")

        text = await self._opening_text(document_id, workspace_id)
        if not text.strip():
            log.info("classification_skipped_empty", document_id=str(document_id))
            return None

        try:
            provider, spec = self._router.resolve(
                task=TaskType.CLASSIFICATION, preferred_model=preferred_model
            )
            result = await provider.generate(
                messages=[
                    ChatMessage(
                        role="user",
                        content=f"Filename: {document.filename}\n\n{text}",
                    )
                ],
                model=spec.id,
                system=CLASSIFY_PROMPT,
                max_tokens=1024,
                json_schema=CLASSIFY_SCHEMA,
            )
            payload = json.loads(result.text)
        except (ProviderError, json.JSONDecodeError, KeyError, TypeError):
            log.info("classification_unavailable", document_id=str(document_id))
            return None
        except Exception:
            log.warning("classification_failed", document_id=str(document_id), exc_info=True)
            return None

        return await self._persist(
            document=document,
            workspace_id=workspace_id,
            team_id=team_id,
            payload=payload,
            model_used=result.model,
        )

    async def _persist(
        self,
        *,
        document: Document,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID | None,
        payload: dict,
        model_used: str,
    ) -> ClassificationResponse:
        kind = _parse_kind(payload.get("kind"))
        topics = [
            str(t).strip().lower()[:40] for t in (payload.get("topics") or [])[:8] if str(t).strip()
        ]

        # Read off the document before any rollback: rolling back expires every
        # object in the session, and touching an expired attribute afterwards
        # triggers lazy IO that raises MissingGreenlet under asyncio.
        document_id = document.id
        filename = document.filename

        def apply(row: DocumentClassification) -> None:
            row.kind = kind
            row.title = (payload.get("title") or filename)[:300]
            row.summary = (payload.get("summary") or "")[:2000] or None
            row.topics = topics
            row.effective_date = _parse_date(payload.get("effective_date"))
            row.confidence = float(payload.get("confidence") or 0.0)
            row.model_used = model_used
            if team_id is not None:
                row.team_id = team_id

        existing = await self._classifications.get_for_document(document_id, workspace_id)

        if existing is None:
            # Ingestion classifies in the background while a user can ask for a
            # re-classification of the same document, so two callers can both
            # find no row and both insert. The unique index settles it; the
            # loser re-reads and updates instead of surfacing a 500.
            candidate = DocumentClassification(
                workspace_id=workspace_id,
                document_id=document_id,
                team_id=team_id,
            )
            apply(candidate)
            try:
                existing = await self._classifications.add(candidate)
                await self._classifications.commit()
            except IntegrityError:
                await self._classifications.rollback()
                existing = await self._classifications.get_for_document(document_id, workspace_id)
                if existing is None:
                    raise
                log.info("classification_raced", document_id=str(document_id))
                existing.version += 1
                apply(existing)
                await self._classifications.commit()
        else:
            # Re-running the pass updates in place and counts as a new version,
            # rather than accumulating rows nothing reads.
            existing.version += 1
            apply(existing)
            await self._classifications.commit()

        await self._classifications.refresh(existing)

        log.info(
            "document_classified",
            document_id=str(document_id),
            kind=kind.value,
            topics=topics,
            version=existing.version,
        )
        return ClassificationResponse.model_validate(existing)

    async def _opening_text(self, document_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
        """The document's first chunks, reassembled.

        Uses the chunks rather than re-reading and re-parsing the original
        file: ingestion already did that work, and the chunk text is what
        retrieval sees anyway.
        """
        chunks = await self._chunks.list_visible_for_document(document_id, workspace_id)
        text = ""
        for chunk in chunks:
            text += chunk.content + "\n\n"
            if len(text) >= CLASSIFY_CHARS:
                break
        return text[:CLASSIFY_CHARS]

    async def map(
        self,
        *,
        workspace_id: uuid.UUID,
        kind: DocumentKind | None = None,
        team_id: uuid.UUID | None = None,
        topic: str | None = None,
    ) -> KnowledgeMapResponse:
        """What this team does, as derived from what it has uploaded."""
        rows = await self._classifications.list_by_kind(
            workspace_id, kind=kind, team_id=team_id, topic=topic
        )
        return KnowledgeMapResponse(
            counts_by_kind=await self._classifications.counts_by_kind(workspace_id),
            topics=await self._classifications.topics(workspace_id),
            documents=[
                ClassifiedDocument(
                    document_id=document.id,
                    filename=document.filename,
                    kind=classification.kind,
                    title=classification.title,
                    summary=classification.summary,
                    topics=classification.topics,
                    effective_date=classification.effective_date,
                    team_id=classification.team_id,
                    created_at=document.created_at,
                )
                for classification, document in rows
            ],
            unclassified_count=len(
                await self._classifications.unclassified_document_ids(workspace_id)
            ),
        )

    async def get_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> ClassificationResponse:
        row = await self._classifications.get_for_document(document_id, workspace_id)
        if row is None:
            raise NotFoundError("This document has not been classified.")
        return ClassificationResponse.model_validate(row)


def _parse_kind(value) -> DocumentKind:
    try:
        return DocumentKind(str(value).strip().lower())
    except ValueError:
        return DocumentKind.OTHER


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None
