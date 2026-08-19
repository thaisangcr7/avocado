"""Deepgram adapter — batch over HTTP, live over WebSocket.

Written against Deepgram's REST/WS API directly rather than through their SDK.
The surface actually used here is small (one POST, one socket), and keeping it
explicit means the adapter has no opinion about SDK versioning and stays easy
to swap.

The live path is the fiddly one. Two details that are easy to get wrong:

* Deepgram must be told when the audio is finished (`CloseStream`), or the
  socket lingers and the last utterance is never finalised.
* Sending audio and reading results have to happen concurrently. Doing them in
  sequence deadlocks the moment the provider's receive buffer fills.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx
import websockets

from app.clients.stt.base import Transcription, TranscriptionClient, TranscriptSegment
from app.core.errors import ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)

BATCH_URL = "https://api.deepgram.com/v1/listen"
STREAM_URL = "wss://api.deepgram.com/v1/listen"

DEFAULT_MODEL = "nova-2"
BATCH_TIMEOUT_SECONDS = 300.0

# How long to wait for Deepgram to finalise after the audio ends. Without a
# bound, a provider that never sends the closing frame hangs the request.
_DRAIN_TIMEOUT_SECONDS = 10.0


class DeepgramClient(TranscriptionClient):
    name = "deepgram"

    def __init__(self, api_key: str | None, *, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ProviderError("DEEPGRAM_API_KEY is not configured.")
        self._api_key = api_key
        self._model = model

    async def available(self) -> bool:
        return bool(self._api_key)

    # -- batch --------------------------------------------------------------

    async def transcribe(
        self, audio: bytes, *, content_type: str, language: str | None = None
    ) -> Transcription:
        params = {
            "model": self._model,
            "smart_format": "true",
            "punctuate": "true",
            # Utterance-level output gives speaker turns, which make a long
            # meeting transcript far more readable as a document.
            "utterances": "true",
            "diarize": "true",
        }
        if language:
            params["language"] = language
        else:
            params["detect_language"] = "true"

        try:
            async with httpx.AsyncClient(timeout=BATCH_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{BATCH_URL}?{urlencode(params)}",
                    headers={
                        "Authorization": f"Token {self._api_key}",
                        "Content-Type": content_type,
                    },
                    content=audio,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            log.warning("deepgram_batch_error", status=exc.response.status_code)
            raise ProviderError(f"Transcription failed ({exc.response.status_code}).") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the transcription service.") from exc

        return _parse_batch_response(payload, self._model)

    # -- streaming ----------------------------------------------------------

    async def stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        encoding: str | None = None,
        sample_rate: int | None = None,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        params: dict[str, str] = {
            "model": self._model,
            "smart_format": "true",
            "punctuate": "true",
            # Interim results are the whole point of a live view: without them
            # nothing appears until the speaker pauses.
            "interim_results": "true",
            "endpointing": "300",
        }
        if language:
            params["language"] = language
        if encoding:
            params["encoding"] = encoding
        if sample_rate:
            params["sample_rate"] = str(sample_rate)

        url = f"{STREAM_URL}?{urlencode(params)}"
        segments: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()

        try:
            async with websockets.connect(
                url, additional_headers={"Authorization": f"Token {self._api_key}"}
            ) as socket:

                async def pump_audio() -> None:
                    """Forward microphone audio, then tell Deepgram it is done."""
                    try:
                        async for chunk in audio_chunks:
                            if chunk:
                                await socket.send(chunk)
                    finally:
                        # Without CloseStream the final utterance is never
                        # finalised and the socket just idles. A socket the
                        # client already dropped is fine to fail on here.
                        with contextlib.suppress(websockets.WebSocketException):
                            await socket.send(json.dumps({"type": "CloseStream"}))

                async def pump_results() -> None:
                    try:
                        async for raw in socket:
                            segment = _parse_stream_message(raw)
                            if segment is not None:
                                await segments.put(segment)
                    finally:
                        await segments.put(None)

                # Concurrent by necessity: sending and receiving in sequence
                # deadlocks once the provider's buffer fills.
                sender = asyncio.create_task(pump_audio())
                receiver = asyncio.create_task(pump_results())

                try:
                    while True:
                        try:
                            segment = await asyncio.wait_for(
                                segments.get(), timeout=_DRAIN_TIMEOUT_SECONDS
                            )
                        except TimeoutError:
                            log.warning("deepgram_stream_stalled")
                            break
                        if segment is None:
                            break
                        yield segment
                finally:
                    for task in (sender, receiver):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)

        except websockets.WebSocketException as exc:
            log.warning("deepgram_stream_error", error=str(exc))
            raise ProviderError("The transcription stream failed.") from exc
        except OSError as exc:
            raise ProviderError("Could not reach the transcription service.") from exc


def _parse_batch_response(payload: dict, model: str) -> Transcription:
    """Pull the transcript out of Deepgram's nested result shape."""
    results = payload.get("results", {})
    channels = results.get("channels") or []
    alternative = (channels[0].get("alternatives") or [{}])[0] if channels else {}

    utterances = [
        {
            "speaker": u.get("speaker"),
            "text": u.get("transcript", ""),
            "start": u.get("start", 0.0),
            "end": u.get("end", 0.0),
        }
        for u in results.get("utterances") or []
    ]

    # Prefer the speaker-attributed rendering when diarisation produced one —
    # "Speaker 0: ..." reads far better in a retrieved chunk than a wall of
    # undifferentiated text.
    if utterances:
        text = "\n".join(
            f"Speaker {u['speaker']}: {u['text']}" if u["speaker"] is not None else u["text"]
            for u in utterances
            if u["text"]
        )
    else:
        text = alternative.get("transcript", "")

    metadata = payload.get("metadata", {})
    return Transcription(
        text=text,
        duration_seconds=metadata.get("duration"),
        confidence=float(alternative.get("confidence") or 0.0),
        language=(channels[0].get("detected_language") if channels else None),
        model=metadata.get("model_info", {}).get("name") or model,
        utterances=utterances,
    )


def _parse_stream_message(raw: str | bytes) -> TranscriptSegment | None:
    """Turn one socket frame into a segment, or None if it carries no text."""
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if event.get("type") not in (None, "Results"):
        return None

    alternatives = (event.get("channel") or {}).get("alternatives") or []
    if not alternatives:
        return None

    text = alternatives[0].get("transcript", "")
    if not text:
        return None

    start = float(event.get("start") or 0.0)
    return TranscriptSegment(
        text=text,
        is_final=bool(event.get("is_final")),
        confidence=float(alternatives[0].get("confidence") or 0.0),
        start_seconds=start,
        end_seconds=start + float(event.get("duration") or 0.0),
    )
