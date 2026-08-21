"""Conversation and message routes, including the SSE streaming turn."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.deps import ChatServiceDep, WorkspaceContextDep
from app.core.errors import AvocadoError
from app.core.logging import get_logger
from app.schemas.chat import (
    ChatTurnResponse,
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
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
    return await service.messages(conversation_id, context.id)


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
