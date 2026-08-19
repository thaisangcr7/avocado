"""Voice routes: recorded audio, and the live dictation socket.

Two different jobs:

* `POST /workspaces/{id}/voice` — a finished recording becomes a transcript,
  and that transcript becomes an ordinary retrievable document.
* `WS /voice/stream` — the microphone, transcribed as the user speaks, so the
  text can be dropped into the chat box. Nothing is persisted here; this is
  dictation, not a recording.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, WebSocket, status
from fastapi.websockets import WebSocketDisconnect
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import (
    CurrentUserDep,
    DocumentsDep,
    SettingsDep,
    StorageDep,
    VoiceRecordingsDep,
    WorkspaceContextDep,
)
from app.core.config import Settings, get_settings
from app.core.errors import PayloadTooLargeError, ProviderError
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.session import session_scope
from app.repositories.tenancy import WorkspaceRepository
from app.schemas.common import MessageResponse
from app.schemas.voice import (
    VoiceAuthFrame,
    VoiceCapabilityResponse,
    VoiceRecordingResponse,
    VoiceUploadResponse,
)
from app.services.voice_service import VoiceService

log = get_logger(__name__)

router = APIRouter(tags=["voice"])


def get_voice_service(
    request: Request,
    recordings: VoiceRecordingsDep,
    documents: DocumentsDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> VoiceService:
    return VoiceService(
        recordings=recordings,
        documents=documents,
        storage=storage,
        transcriber=request.app.state.transcriber,
        max_audio_bytes=settings.max_audio_bytes,
    )


VoiceServiceDep = Annotated[VoiceService, Depends(get_voice_service)]


@router.get("/voice/capabilities", response_model=VoiceCapabilityResponse)
async def voice_capabilities(
    request: Request, _user: CurrentUserDep, settings: SettingsDep
) -> VoiceCapabilityResponse:
    """What voice features are actually available.

    The client asks first so it can hide the microphone entirely rather than
    offering a button that fails when pressed.
    """
    transcriber = request.app.state.transcriber
    if transcriber is None:
        return VoiceCapabilityResponse(enabled=False)

    return VoiceCapabilityResponse(
        enabled=True,
        provider=transcriber.name,
        live_transcription=True,
        max_audio_mb=settings.max_audio_mb,
        max_stream_seconds=settings.voice_stream_max_seconds,
    )


@router.post(
    "/workspaces/{workspace_id}/voice",
    response_model=VoiceUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_recording(
    request: Request,
    context: WorkspaceContextDep,
    service: VoiceServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> VoiceUploadResponse:
    """Upload a recording. It is transcribed in the background, and the
    transcript becomes a document you can ask questions about."""
    limit = settings.max_audio_bytes
    parts: list[bytes] = []
    total = 0
    # Bounded read: stop at the limit rather than buffering an arbitrarily
    # large body and checking afterwards.
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError(f"Recordings must be {limit // (1024 * 1024)}MB or smaller.")
        parts.append(chunk)

    recording = await service.upload(
        workspace_id=context.id,
        user_id=context.user.id,
        filename=file.filename or "recording.webm",
        content_type=file.content_type or "audio/webm",
        data=b"".join(parts),
    )

    await request.app.state.schedule_transcription(uuid.UUID(str(recording.id)), context.id)
    return VoiceUploadResponse(recording=recording)


@router.get("/workspaces/{workspace_id}/voice", response_model=list[VoiceRecordingResponse])
async def list_recordings(
    context: WorkspaceContextDep, service: VoiceServiceDep
) -> list[VoiceRecordingResponse]:
    return await service.list(context.id)


@router.get(
    "/workspaces/{workspace_id}/voice/{recording_id}",
    response_model=VoiceRecordingResponse,
)
async def get_recording(
    recording_id: uuid.UUID, context: WorkspaceContextDep, service: VoiceServiceDep
) -> VoiceRecordingResponse:
    return await service.get(recording_id, context.id)


@router.delete("/workspaces/{workspace_id}/voice/{recording_id}", response_model=MessageResponse)
async def delete_recording(
    recording_id: uuid.UUID, context: WorkspaceContextDep, service: VoiceServiceDep
) -> MessageResponse:
    await service.delete(recording_id, context.id)
    return MessageResponse(message="Recording deleted.")


# ---------------------------------------------------------------------------
# Live dictation
# ---------------------------------------------------------------------------

# Close codes. 1008 is "policy violation", which is what the WebSocket spec
# gives us for an auth failure.
_CLOSE_POLICY = status.WS_1008_POLICY_VIOLATION
_CLOSE_NORMAL = status.WS_1000_NORMAL_CLOSURE


async def _authenticate(
    websocket: WebSocket, settings: Settings
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Authenticate the socket from its first frame.

    The token is sent in the message body rather than a query parameter: URLs
    end up in access logs, proxy history and browser history, and a bearer
    token in any of those is a credential leak.

    Returns (user_id, workspace_id), or None if the socket was closed.
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        await websocket.close(code=_CLOSE_POLICY, reason="Authentication timed out.")
        return None

    try:
        frame = VoiceAuthFrame.model_validate(raw)
    except PydanticValidationError:
        await websocket.close(code=_CLOSE_POLICY, reason="Expected an auth frame.")
        return None

    try:
        payload = decode_token(settings=settings, token=frame.token, expected_type="access")
        user_id = uuid.UUID(payload["sub"])
    except Exception:
        await websocket.close(code=_CLOSE_POLICY, reason="Invalid token.")
        return None

    # Workspace access is checked here for the same reason it is checked on
    # every HTTP route: a workspace id from the client proves nothing.
    async with session_scope(websocket.app.state.session_factory) as session:
        workspace = await WorkspaceRepository(session).get_for_user(frame.workspace_id, user_id)
    if workspace is None:
        await websocket.close(code=_CLOSE_POLICY, reason="Workspace not found.")
        return None

    websocket.state.auth_frame = frame
    return user_id, frame.workspace_id


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    """Live microphone transcription.

    Protocol:
      client → `{"type":"auth","token":…,"workspace_id":…}`  (required first)
      client → binary audio frames
      client → `{"type":"stop"}` to finish
      server → `{"type":"ready"}`
      server → `{"type":"transcript","text":…,"is_final":bool}`
      server → `{"type":"done"}` or `{"type":"error","detail":…}`

    Nothing is persisted. This exists so a user can speak a question instead of
    typing it; the text lands in the chat box and is sent like any other.
    """
    settings = get_settings()
    await websocket.accept()

    authenticated = await _authenticate(websocket, settings)
    if authenticated is None:
        return
    user_id, workspace_id = authenticated

    transcriber = websocket.app.state.transcriber
    if transcriber is None:
        await websocket.send_json(
            {"type": "error", "detail": "Voice transcription is not configured."}
        )
        await websocket.close(code=_CLOSE_NORMAL)
        return

    frame: VoiceAuthFrame = websocket.state.auth_frame
    await websocket.send_json({"type": "ready"})

    stop = asyncio.Event()

    async def audio_from_client():
        """Yield audio frames until the client stops, disconnects, or the
        session outlives its ceiling."""
        deadline = asyncio.get_running_loop().time() + settings.voice_stream_max_seconds
        while not stop.is_set():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                log.info("voice_stream_max_duration", user_id=str(user_id))
                break
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=min(remaining, 30.0))
            except TimeoutError:
                continue
            except (WebSocketDisconnect, RuntimeError):
                break

            if message.get("type") == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                yield data
            # The only control frame that matters mid-stream.
            elif (text := message.get("text")) is not None and '"stop"' in text:
                break

    try:
        async for segment in transcriber.stream(
            audio_from_client(),
            encoding=frame.encoding,
            sample_rate=frame.sample_rate,
            language=frame.language,
        ):
            await websocket.send_json(
                {
                    "type": "transcript",
                    "text": segment.text,
                    "is_final": segment.is_final,
                    "confidence": round(segment.confidence, 4),
                }
            )
        await websocket.send_json({"type": "done"})

    except ProviderError as exc:
        await websocket.send_json({"type": "error", "detail": exc.detail})
    except WebSocketDisconnect:
        log.info("voice_stream_client_disconnected", user_id=str(user_id))
        return
    except Exception:
        log.exception("voice_stream_failed", workspace_id=str(workspace_id))
        # The socket is already open, so an exception handler cannot set a
        # status code — an error frame is the only way to say what happened.
        with contextlib.suppress(RuntimeError):
            await websocket.send_json(
                {"type": "error", "detail": "The transcription stream failed."}
            )
    finally:
        stop.set()
        # The client may already be gone; closing a closed socket is not an
        # error worth surfacing.
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=_CLOSE_NORMAL)
