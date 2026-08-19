"""Ollama adapter — local models, no API key, no cost.

Deliberately thin: Ollama exposes a plain HTTP API, so there is no SDK to wrap.
Model specs are discovered at runtime because what is available depends on what
the operator has pulled.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.clients.llm.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ModelSpec,
    StreamChunk,
    Usage,
)
from app.core.errors import ProviderError


def _spec(model_id: str) -> ModelSpec:
    return ModelSpec(
        id=model_id,
        provider="ollama",
        display_name=model_id,
        context_window=8192,
        max_output_tokens=4096,
        input_cost_per_mtok=0.0,  # self-hosted: no per-token cost
        output_cost_per_mtok=0.0,
        supports_vision=False,
        tier="fast",
    )


def _to_ollama_messages(messages: list[ChatMessage], system: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.images:
            entry["images"] = [img.data_b64 for img in m.images]
        out.append(entry)
    return out


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, *, timeout: float = 180.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._cached_models: list[ModelSpec] | None = None

    def models(self) -> list[ModelSpec]:
        # Populated by `refresh_models()`; empty until then rather than lying
        # about what is installed.
        return self._cached_models or []

    async def refresh_models(self) -> list[ModelSpec]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the Ollama server.") from exc

        self._cached_models = [_spec(m["name"]) for m in data.get("models", [])]
        return self._cached_models

    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _to_ollama_messages(messages, system),
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if json_schema is not None:
            payload["format"] = json_schema

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Ollama request failed.") from exc

        return CompletionResult(
            text=data.get("message", {}).get("content", ""),
            model=model,
            usage=Usage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            ),
            stop_reason=data.get("done_reason"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": model,
            "messages": _to_ollama_messages(messages, system),
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        usage = Usage()
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("POST", f"{self._base_url}/api/chat", json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("done"):
                        usage = Usage(
                            input_tokens=event.get("prompt_eval_count", 0),
                            output_tokens=event.get("eval_count", 0),
                        )
                        break
                    content = event.get("message", {}).get("content", "")
                    if content:
                        yield StreamChunk(text=content)
        except httpx.HTTPError as exc:
            raise ProviderError("Ollama stream failed.") from exc

        yield StreamChunk(done=True, model=model, usage=usage, stop_reason="stop")

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
