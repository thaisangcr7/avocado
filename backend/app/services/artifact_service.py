"""Artifact creation, versioning and retrieval.

The only interesting rule here is versioning: an edit appends rather than
overwrites, so the panel can show what a document looked like three revisions
ago instead of only its current state.
"""

from __future__ import annotations

import uuid

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.artifacts import Artifact
from app.models.enums import ArtifactAuthor, ArtifactKind
from app.repositories.artifacts import ArtifactRepository
from app.schemas.artifacts import (
    ArtifactDetailResponse,
    ArtifactForCreate,
    ArtifactForUpdate,
    ArtifactResponse,
    ArtifactVersionResponse,
)

log = get_logger(__name__)


class ArtifactService:
    def __init__(self, *, artifacts: ArtifactRepository) -> None:
        self._artifacts = artifacts

    async def create(
        self,
        *,
        workspace_id: uuid.UUID,
        payload: ArtifactForCreate,
        user_id: uuid.UUID | None,
        author: ArtifactAuthor = ArtifactAuthor.USER,
        model_used: str | None = None,
    ) -> ArtifactResponse:
        # Version 1 roots its own lineage, so the lineage id *is* the first
        # version's id. Generated here rather than left to the column default,
        # because both columns have to be set before the insert.
        artifact_id = uuid.uuid4()
        artifact = Artifact(
            id=artifact_id,
            workspace_id=workspace_id,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            created_by_user_id=user_id,
            lineage_id=artifact_id,
            version=1,
            kind=payload.kind,
            author=author,
            title=payload.title,
            filename=payload.filename,
            content=payload.content,
            model_used=model_used,
        )

        await self._artifacts.add(artifact)
        await self._artifacts.commit()
        await self._artifacts.refresh(artifact)

        log.info(
            "artifact_created",
            artifact_id=str(artifact.id),
            kind=artifact.kind.value,
            author=author.value,
        )
        return ArtifactResponse.model_validate(artifact)

    async def revise(
        self,
        *,
        artifact_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: ArtifactForUpdate,
        user_id: uuid.UUID | None,
        author: ArtifactAuthor = ArtifactAuthor.USER,
        model_used: str | None = None,
    ) -> ArtifactResponse:
        """Append a new version. The previous one stays readable."""
        previous = await self._artifacts.get_scoped(artifact_id, workspace_id)
        if previous is None:
            raise NotFoundError("Artifact not found.")

        highest = await self._artifacts.latest_version_number(previous.lineage_id, workspace_id)

        revision = Artifact(
            workspace_id=workspace_id,
            conversation_id=previous.conversation_id,
            message_id=previous.message_id,
            created_by_user_id=user_id,
            lineage_id=previous.lineage_id,
            version=(highest or previous.version) + 1,
            parent_id=previous.id,
            kind=previous.kind,
            author=author,
            title=payload.title or previous.title,
            filename=previous.filename,
            content=payload.content,
            model_used=model_used,
        )
        await self._artifacts.add(revision)
        await self._artifacts.commit()
        await self._artifacts.refresh(revision)

        log.info(
            "artifact_revised",
            artifact_id=str(revision.id),
            lineage_id=str(revision.lineage_id),
            version=revision.version,
        )
        return ArtifactResponse.model_validate(revision)

    async def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID | None = None,
    ) -> list[ArtifactResponse]:
        rows = await self._artifacts.latest_for_workspace(
            workspace_id, conversation_id=conversation_id
        )
        return [ArtifactResponse.model_validate(row) for row in rows]

    async def get(self, artifact_id: uuid.UUID, workspace_id: uuid.UUID) -> ArtifactDetailResponse:
        artifact = await self._artifacts.get_scoped(artifact_id, workspace_id)
        if artifact is None:
            raise NotFoundError("Artifact not found.")

        history = await self._artifacts.versions(artifact.lineage_id, workspace_id)
        return ArtifactDetailResponse(
            **ArtifactResponse.model_validate(artifact).model_dump(),
            versions=[ArtifactVersionResponse.model_validate(v) for v in history],
        )

    @staticmethod
    def media_type_for(kind: ArtifactKind) -> str:
        """What a download should be served as.

        HTML is deliberately *not* served as text/html: a browser navigating
        straight to it would run model-written script on this origin. It
        downloads instead, and the in-app viewer renders it inside a sandboxed,
        null-origin frame.
        """
        return {
            ArtifactKind.HTML: "application/octet-stream",
            ArtifactKind.MARKDOWN: "text/markdown; charset=utf-8",
            ArtifactKind.CODE: "text/plain; charset=utf-8",
            ArtifactKind.TABLE: "text/csv; charset=utf-8",
            ArtifactKind.CHART: "image/png",
        }.get(kind, "application/octet-stream")
