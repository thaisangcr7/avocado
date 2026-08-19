"""Voice resources."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import TranscriptStatus
from app.schemas.common import ApiModel


class VoiceRecordingResponse(ApiModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    # Set once the transcript has been turned into a retrievable document.
    document_id: uuid.UUID | None
    duration_seconds: float | None
    transcript_status: TranscriptStatus
    transcript: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class VoiceUploadResponse(BaseModel):
    recording: VoiceRecordingResponse
    message: str = "Transcription started."


class VoiceCapabilityResponse(BaseModel):
    """What the client should offer, so the UI never shows a dead mic button."""

    enabled: bool
    provider: str | None = None
    live_transcription: bool = False
    max_audio_mb: int = 0
    max_stream_seconds: int = 0


# --- WebSocket frames -------------------------------------------------------
# The live socket is a small protocol of its own; naming the frames keeps both
# ends honest about what is being exchanged.


class VoiceAuthFrame(BaseModel):
    """First frame the client must send.

    The token travels in the message body rather than a query parameter,
    because URLs land in access logs and proxy history.
    """

    type: str = Field(pattern="^auth$")
    token: str
    workspace_id: uuid.UUID
    encoding: str | None = None
    sample_rate: int | None = Field(default=None, ge=8000, le=48000)
    language: str | None = Field(default=None, max_length=10)
