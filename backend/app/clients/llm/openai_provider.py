"""OpenAI adapter — the second provider, for comparison and failover."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import openai

from app.clients.llm.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ModelSpec,
    StreamChunk,
    Usage,
)
from app.core.errors import ProviderCredentialError, ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)


def _classify(exc: openai.APIStatusError) -> ProviderError:
    """Turn an OpenAI status error into the right kind of ProviderError.

    Only conditions a retry cannot clear are credential errors. A plain 429 is
    ordinary rate limiting and must stay transient: treating it as permanent
    would let a burst of traffic disable the provider for everyone.
    """
    detail = f"OpenAI request failed ({exc.status_code})."
    if exc.status_code in (401, 403):
        return ProviderCredentialError(detail)
    if exc.status_code == 429 and _is_quota_exhausted(exc):
        return ProviderCredentialError("OpenAI quota is exhausted for this account.")
    return ProviderError(detail)


def _is_quota_exhausted(exc: openai.APIStatusError) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code") == "insufficient_quota":
            return True
    return "insufficient_quota" in str(exc)


OPENAI_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="gpt-4o",
        provider="openai",
        display_name="GPT-4o",
        context_window=128_000,
        max_output_tokens=16_384,
        input_cost_per_mtok=2.50,
        output_cost_per_mtok=10.00,
        tier="balanced",
    ),
    ModelSpec(
        id="gpt-4o-mini",
        provider="openai",
        display_name="GPT-4o mini",
        context_window=128_000,
        max_output_tokens=16_384,
        input_cost_per_mtok=0.15,
        output_cost_per_mtok=0.60,
        tier="fast",
    ),
]


def _to_openai_messages(messages: list[ChatMessage], system: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if not m.images:
            out.append({"role": m.role, "content": m.content})
            continue
        parts: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img.media_type};base64,{img.data_b64}"},
            }
            for img in m.images
        ]
        parts.append({"type": "text", "text": m.content})
        out.append({"role": m.role, "content": parts})
    return out


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None, *, timeout: float = 120.0) -> None:
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not configured.")
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout)

    def models(self) -> list[ModelSpec]:
        return OPENAI_MODELS

    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        model: str = "gpt-4o",
        system: str | None = None,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
        # Accepted and ignored: this vendor hosts no server-side tools. The
        # parameter is part of the interface so a caller never has to know
        # which provider it reached, and the tool registry is what stops one
        # being offered where it cannot run.
        server_tools: list[str] | None = None,
    ) -> CompletionResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_openai_messages(messages, system),
        }
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "strict": True,
                    "schema": json_schema,
                },
            }

        started = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            log.warning("openai_api_error", status=exc.status_code, model=model)
            raise _classify(exc) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not reach the OpenAI API.") from exc

        choice = response.choices[0]
        usage = response.usage
        return CompletionResult(
            text=choice.message.content or "",
            model=response.model,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            stop_reason=choice.finish_reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        model: str = "gpt-4o",
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=_to_openai_messages(messages, system),
                stream=True,
                stream_options={"include_usage": True},
            )
            usage = Usage()
            finish_reason: str | None = None
            async for event in stream:
                if event.usage:
                    usage = Usage(
                        input_tokens=event.usage.prompt_tokens,
                        output_tokens=event.usage.completion_tokens,
                    )
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                if event.choices[0].finish_reason:
                    finish_reason = event.choices[0].finish_reason
                if delta and delta.content:
                    yield StreamChunk(text=delta.content)
        except openai.APIStatusError as exc:
            raise _classify(exc) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not reach the OpenAI API.") from exc

        yield StreamChunk(done=True, model=model, usage=usage, stop_reason=finish_reason)
