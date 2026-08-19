"""Builds the configured transcription client."""

from __future__ import annotations

from app.clients.stt.base import TranscriptionClient
from app.clients.stt.deepgram import DeepgramClient
from app.core.config import Settings


def build_transcription_client(settings: Settings) -> TranscriptionClient | None:
    """Return the configured STT client, or None when voice is disabled.

    None rather than a stub: a voice endpoint that silently returns nothing is
    worse than one that says transcription is not configured.
    """
    if settings.stt_provider == "disabled" or not settings.deepgram_api_key:
        return None
    return DeepgramClient(settings.deepgram_api_key, model=settings.deepgram_model)
