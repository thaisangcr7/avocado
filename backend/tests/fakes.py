"""Test doubles for the external clients.

Real providers are never called from tests: they cost money, need credentials,
and are non-deterministic. These fakes implement the same interfaces, so what
is under test is the application's own logic rather than a vendor's.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.clients.llm.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ModelSpec,
    StreamChunk,
    Usage,
)
from app.clients.sandbox.base import Sandbox, SandboxDataset, SandboxLimits, SandboxResult
from app.clients.stt.base import Transcription, TranscriptionClient, TranscriptSegment

FAKE_MODELS = [
    ModelSpec(
        id="fake-frontier",
        provider="fake",
        display_name="Fake Frontier",
        context_window=200_000,
        max_output_tokens=8192,
        input_cost_per_mtok=5.0,
        output_cost_per_mtok=25.0,
        tier="frontier",
    ),
    ModelSpec(
        id="fake-fast",
        provider="fake",
        display_name="Fake Fast",
        context_window=100_000,
        max_output_tokens=4096,
        input_cost_per_mtok=1.0,
        output_cost_per_mtok=5.0,
        tier="fast",
    ),
]


class FakeLLMProvider(LLMProvider):
    """Returns scripted responses and records every call it received."""

    name = "fake"
    # Declared so tests can exercise the server-tool path. The real check is
    # capability, not vendor, which is exactly what this stands in for.
    server_tools = frozenset({"web_search", "web_fetch"})

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[dict[str, Any]] = []
        self.default_response = "This is a grounded answer. [1]"

    def models(self) -> list[ModelSpec]:
        return FAKE_MODELS

    def _next(self) -> str:
        return self.responses.pop(0) if self.responses else self.default_response

    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
        server_tools: list[str] | None = None,
    ) -> CompletionResult:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "messages": [m.content for m in messages],
                "json_schema": json_schema,
                "images": sum(len(m.images) for m in messages),
                # Recorded so a test can assert which server tools were offered.
                # A fake that silently drops a new argument makes the caller
                # look correct while the real provider never receives it.
                "server_tools": list(server_tools or []),
            }
        )
        text = self._next()
        # A schema-constrained call returns whatever was scripted, unchanged.
        # Coercing non-JSON into some default shape would make it impossible to
        # test how callers handle a provider that ignored the schema — and
        # would silently hand every schema call the *analysis* shape, which is
        # only correct for one of them.
        if json_schema is not None and text is self.default_response:
            text = json.dumps({"code": "result = df.sum()", "explanation": "Default."})
        return CompletionResult(
            text=text,
            model=model,
            usage=Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
            latency_ms=5,
        )

    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append({"model": model, "system": system, "streamed": True})
        text = self._next()
        for word in text.split(" "):
            yield StreamChunk(text=word + " ")
        yield StreamChunk(
            done=True,
            model=model,
            usage=Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        )


class FakeSandbox(Sandbox):
    """A sandbox that returns a scripted result without executing anything.

    Used to test how `AnalysisService` handles success, failure and retry. The
    real Docker sandbox is tested separately, against actual containers.
    """

    name = "fake"

    def __init__(self, results: list[SandboxResult] | None = None, *, up: bool = True) -> None:
        self.results = results or []
        self.up = up
        self.executed_code: list[str] = []

    async def available(self) -> bool:
        return self.up

    async def run(
        self, *, code: str, datasets: list[SandboxDataset], limits: SandboxLimits
    ) -> SandboxResult:
        self.executed_code.append(code)
        if self.results:
            return self.results.pop(0)
        return SandboxResult(
            success=True,
            stdout="total: 450",
            tables=[
                {
                    "name": "result",
                    "columns": ["region", "revenue"],
                    "rows": [["North", 250], ["South", 200]],
                    "total_rows": 2,
                    "truncated": False,
                }
            ],
            execution_ms=42,
        )


class FakeTranscriptionClient(TranscriptionClient):
    """Returns scripted transcripts without touching a speech API.

    Real STT is metered, non-deterministic, and needs audio fixtures; what is
    under test here is how the application handles a transcript, not whether a
    vendor can recognise speech.
    """

    name = "fake-stt"

    def __init__(
        self,
        transcription: Transcription | None = None,
        segments: list[TranscriptSegment] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.transcription = transcription or Transcription(
            text="Speaker 0: We agreed to ship the analysis engine first.",
            duration_seconds=12.5,
            confidence=0.98,
            language="en",
            model="fake-nova",
            utterances=[
                {
                    "speaker": 0,
                    "text": "We agreed to ship the analysis engine first.",
                    "start": 0.0,
                    "end": 12.5,
                }
            ],
        )
        self.segments = segments or [
            TranscriptSegment(text="what is", is_final=False, confidence=0.6),
            TranscriptSegment(text="what is the", is_final=False, confidence=0.7),
            TranscriptSegment(
                text="What is the remote work policy?", is_final=True, confidence=0.95
            ),
        ]
        self.error = error
        self.received_audio: list[bytes] = []
        self.calls = 0

    async def transcribe(
        self, audio: bytes, *, content_type: str, language: str | None = None
    ) -> Transcription:
        self.calls += 1
        self.received_audio.append(audio)
        if self.error is not None:
            raise self.error
        return self.transcription

    async def stream(
        self,
        audio_chunks,
        *,
        encoding: str | None = None,
        sample_rate: int | None = None,
        language: str | None = None,
    ):
        if self.error is not None:
            raise self.error
        # Drain the client's audio so the producing side completes, exactly as
        # a real provider would.
        async for chunk in audio_chunks:
            self.received_audio.append(chunk)
        for segment in self.segments:
            yield segment
