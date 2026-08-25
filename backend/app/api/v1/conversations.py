"""Conversation and message routes, including the SSE streaming turn."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.api.deps import ChatServiceDep, EnhanceServiceDep, WorkspaceContextDep
from app.core.errors import AvocadoError
from app.core.logging import get_logger
from app.schemas.chat import (
    ChatTurnResponse,
    ConversationCreate,
    ConversationFlags,
    ConversationPage,
    ConversationResponse,
    ConversationUpdate,
    EnhanceRequest,
    EnhanceResponse,
    FeedbackRequest,
    MessageCreate,
    MessageResponse,
)
from app.schemas.common import MessageResponse as Ack

log = get_logger(__name__)

router = APIRouter(tags=["conversations"])


@router.post(
    "/workspaces/{workspace_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> ConversationResponse:
    return await service.create(context.id, context.user.id, payload)


@router.get(
    "/workspaces/{workspace_id}/conversations",
    response_model=list[ConversationResponse],
)
async def list_conversations(
    context: WorkspaceContextDep, service: ChatServiceDep
) -> list[ConversationResponse]:
    return await service.list(context.id)


@router.get(
    "/workspaces/{workspace_id}/conversations/history",
    response_model=ConversationPage,
)
async def conversation_history(
    context: WorkspaceContextDep,
    service: ChatServiceDep,
    which: Literal["all", "active", "archived", "pinned"] = Query(default="all"),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ConversationPage:
    """A page of history: search, filter, and a message count per row."""
    return await service.history(context.id, which=which, search=search, limit=limit, offset=offset)


@router.get(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/export",
    response_class=PlainTextResponse,
)
async def export_conversation(
    conversation_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> PlainTextResponse:
    """The thread as markdown, as an attachment."""
    filename, body = await service.export(conversation_id, context.id)
    return PlainTextResponse(
        body,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # It is user-authored text being handed back; never let a browser
            # sniff it into something it can execute.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/flags",
    response_model=ConversationResponse,
)
async def set_conversation_flags(
    conversation_id: uuid.UUID,
    payload: ConversationFlags,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> ConversationResponse:
    """Pin a thread, or file it away. Only what is sent changes."""
    return await service.set_flags(
        conversation_id, context.id, pinned=payload.pinned, archived=payload.archived
    )


@router.get(
    "/workspaces/{workspace_id}/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    conversation_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> ConversationResponse:
    return await service.get(conversation_id, context.id)


@router.patch(
    "/workspaces/{workspace_id}/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> ConversationResponse:
    return await service.rename(conversation_id, context.id, payload.title)


@router.delete("/workspaces/{workspace_id}/conversations/{conversation_id}", response_model=Ack)
async def delete_conversation(
    conversation_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> Ack:
    await service.delete(conversation_id, context.id)
    return Ack(message="Conversation deleted.")


@router.get(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def list_messages(
    conversation_id: uuid.UUID,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> list[MessageResponse]:
    return await service.messages(conversation_id, context.id, user_id=context.user.id)


@router.post("/workspaces/{workspace_id}/enhance", response_model=EnhanceResponse)
async def enhance_draft(
    payload: EnhanceRequest,
    context: WorkspaceContextDep,
    service: EnhanceServiceDep,
) -> EnhanceResponse:
    """Sharpen a half-typed question before it is sent."""
    rewritten = await service.enhance(payload.draft)
    return EnhanceResponse(
        draft=rewritten,
        original=payload.draft,
        changed=rewritten.strip() != payload.draft.strip(),
    )


@router.put(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/feedback",
    response_model=Ack,
)
async def rate_message(
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> Ack:
    """Say whether an answer was any good. Sending no rating withdraws it."""
    await service.rate(
        message_id=message_id,
        workspace_id=context.id,
        user_id=context.user.id,
        rating=payload.rating,
    )
    return Ack(message="Recorded." if payload.rating else "Withdrawn.")


@router.post(
    "/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
    response_model=ChatTurnResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> ChatTurnResponse:
    """Ask a question. The answer is grounded in this workspace's documents."""
    return await service.send(
        conversation_id=conversation_id,
        workspace_id=context.id,
        org_id=context.org_id,
        user_id=context.user.id,
        preferred_model=context.preferred_model,
        require_grounding=context.require_grounding,
        payload=payload,
    )


@router.post("/workspaces/{workspace_id}/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    context: WorkspaceContextDep,
    service: ChatServiceDep,
) -> StreamingResponse:
    """Same turn, streamed as Server-Sent Events.

    Retrieval turns emit `citations`, streamed `token` events, then `done`.
    Spreadsheet analysis turns emit `analysis_started`,
    `analysis_completed`, then `done`.
    """

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream(
                conversation_id=conversation_id,
                workspace_id=context.id,
                org_id=context.org_id,
                user_id=context.user.id,
                preferred_model=context.preferred_model,
                require_grounding=context.require_grounding,
                payload=payload,
            ):
                yield (f"event: {event['event']}\n" f"data: {json.dumps(event['data'])}\n\n")
        except Exception as exc:
            # The response has already started, so an exception handler cannot
            # change the status code. The only honest option is an error event
            # the client can render in place of the answer.
            log.exception("stream_failed", conversation_id=str(conversation_id))
            # Only our own errors carry a message that is safe to show.
            detail = (
                exc.detail
                if isinstance(exc, AvocadoError)
                else "The response could not be completed."
            )
            yield f"event: error\ndata: {json.dumps({'detail': detail})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells nginx not to buffer, which would defeat streaming entirely.
            "X-Accel-Buffering": "no",
        },
    )
