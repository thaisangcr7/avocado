"""Speech-to-text contract.

Two shapes of the same capability, because they have genuinely different
constraints:

* **Batch** — a finished recording is transcribed in one call. Latency does not
  matter; accuracy and speaker detail do.
* **Streaming** — audio arrives while the user is still speaking, and partial
  results have to come back fast enough to read as live. Accuracy is refined as
  more context arrives, so a segment is `is_final=False` until the provider
  commits to it.

Services depend on this, never on a vendor SDK, so a different STT provider is
a new adapter rather than a change to `VoiceService`.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(slots=True)
class TranscriptSegment:
    """One increment of a live transcription.

    `is_final` is the important field: an interim segment will be *replaced* by
    a later one covering the same audio, so a consumer that appends every
    segment produces duplicated text.
    """

    text: str
    is_final: bool
    confidence: float = 0.0
    start_seconds: float = 0.0
    end_seconds: float = 0.0


@dataclass(slots=True)
class Transcription:
    """The result of transcribing a complete recording."""

    text: str
    duration_seconds: float | None = None
    confidence: float = 0.0
    language: str | None = None
    model: str | None = None
    # [{speaker, text, start, end}] when diarisation is on — kept separate from
    # `text` so the plain transcript stays usable as document content.
    utterances: list[dict] = field(default_factory=list)


class TranscriptionClient(abc.ABC):
    name: str

    @abc.abstractmethod
    async def transcribe(
        self, audio: bytes, *, content_type: str, language: str | None = None
    ) -> Transcription:
        """Transcribe a complete recording."""

    @abc.abstractmethod
    def stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        encoding: str | None = None,
        sample_rate: int | None = None,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        """Transcribe audio as it arrives, yielding interim and final segments."""

    async def available(self) -> bool:
        """Whether this client is configured and can be used."""
        return True
