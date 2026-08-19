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
    ) -> CompletionResult:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "messages": [m.content for m in messages],
                "json_schema": json_schema,
                "images": sum(len(m.images) for m in messages),
            }
        )
        text = self._next()
        # A schema-constrained call must return valid JSON, exactly as the real
        # provider guarantees — otherwise the test would not exercise the
        # parsing path the caller actually has.
        if json_schema is not None and not text.strip().startswith("{"):
            text = json.dumps({"code": text, "explanation": "Fake explanation."})
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
