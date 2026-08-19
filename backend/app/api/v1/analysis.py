"""Analysis routes — natural-language questions computed against a spreadsheet."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    AnalysisServiceDep,
    CurrentUserDep,
    DocumentsDep,
    RunsDep,
    StorageDep,
)
from app.core.errors import NotFoundError
from app.schemas.analysis import AnalysisRequest, AnalysisRunResponse

router = APIRouter(tags=["analysis"])


async def _resolve_document_workspace(
    document_id: uuid.UUID, user: CurrentUserDep, documents: DocumentsDep
) -> uuid.UUID:
    document = await documents.get_for_user(document_id, user.id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document.workspace_id


@router.post(
    "/documents/{document_id}/analyze",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def analyze_document(
    document_id: uuid.UUID,
    payload: AnalysisRequest,
    workspace_id: Annotated[uuid.UUID, Depends(_resolve_document_workspace)],
    user: CurrentUserDep,
    service: AnalysisServiceDep,
) -> AnalysisRunResponse:
    """Ask a question of a spreadsheet and get a computed answer.

    The model writes pandas against the table's schema; the code runs in an
    isolated sandbox with no network, a hard timeout and resource caps. Both
    the code and the result come back, so the answer can be checked.
    """
    return await service.run(
        workspace_id=workspace_id,
        org_id=user.org_id,
        document_id=document_id,
        user_id=user.id,
        question=payload.question,
        table_id=payload.table_id,
        preferred_model=None,
    )


@router.get("/documents/{document_id}/analysis-runs", response_model=list[AnalysisRunResponse])
async def list_analysis_runs(
    document_id: uuid.UUID,
    workspace_id: Annotated[uuid.UUID, Depends(_resolve_document_workspace)],
    service: AnalysisServiceDep,
) -> list[AnalysisRunResponse]:
    return await service.list_for_document(document_id, workspace_id)


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRunResponse)
async def get_analysis_run(
    run_id: uuid.UUID,
    user: CurrentUserDep,
    runs: RunsDep,
    service: AnalysisServiceDep,
) -> AnalysisRunResponse:
    run = await runs.get_for_user(run_id, user.id)
    if run is None:
        raise NotFoundError("Analysis run not found.")
    return await service.get(run_id, run.workspace_id)


@router.get("/analysis-runs/{run_id}/chart")
async def get_analysis_chart(
    run_id: uuid.UUID,
    user: CurrentUserDep,
    runs: RunsDep,
    storage: StorageDep,
) -> Response:
    """The rendered chart, streamed from object storage.

    Served through the API rather than as a storage URL so access stays behind
    the same membership check as the run itself.
    """
    run = await runs.get_for_user(run_id, user.id)
    if run is None or not run.chart_url:
        raise NotFoundError("No chart for this analysis run.")

    return Response(
        content=await storage.get(run.chart_url),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
