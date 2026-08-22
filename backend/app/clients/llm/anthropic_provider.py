"""Claude adapter — the primary provider.

Notes that are easy to get wrong and expensive to rediscover:

* Thinking is adaptive on current models. `budget_tokens` is removed and
  returns a 400, so it is never sent.
* Assistant prefill is rejected on these models; output shape is controlled
  with `output_config.format` instead.
* Streaming is used whenever `max_tokens` is large, because a long
  non-streaming request can exceed the SDK's HTTP timeout.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from app.clients.llm.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ModelSpec,
    StreamChunk,
    Usage,
    WebSource,
)
from app.core.errors import ProviderCredentialError, ProviderError
from app.core.logging import get_logger

log = get_logger(__name__)

# Pricing is per million tokens, matching Anthropic's published rates.
CLAUDE_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="claude-opus-5",
        provider="anthropic",
        display_name="Claude Opus 5",
        context_window=1_000_000,
        max_output_tokens=128_000,
        input_cost_per_mtok=5.00,
        output_cost_per_mtok=25.00,
        tier="frontier",
    ),
    ModelSpec(
        id="claude-sonnet-5",
        provider="anthropic",
        display_name="Claude Sonnet 5",
        context_window=1_000_000,
        max_output_tokens=128_000,
        input_cost_per_mtok=3.00,
        output_cost_per_mtok=15.00,
        tier="balanced",
    ),
    ModelSpec(
        id="claude-haiku-4-5",
        provider="anthropic",
        display_name="Claude Haiku 4.5",
        context_window=200_000,
        max_output_tokens=64_000,
        input_cost_per_mtok=1.00,
        output_cost_per_mtok=5.00,
        tier="fast",
    ),
]

DEFAULT_MODEL = "claude-opus-5"

# Above this, always stream: a single non-streaming request generating tens of
# thousands of tokens can outlast the client HTTP timeout.
_STREAM_THRESHOLD_TOKENS = 8192


def _to_anthropic_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if not m.images:
            out.append({"role": m.role, "content": m.content})
            continue
        # Images first, then the text that refers to them — the ordering the
        # model handles most reliably.
        blocks: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.media_type,
                    "data": img.data_b64,
                },
            }
            for img in m.images
        ]
        blocks.append({"type": "text", "text": m.content})
        out.append({"role": m.role, "content": blocks})
    return out


# Anthropic runs these; there is nothing to implement client-side. The
# _20260209 variants filter results before they reach the context window, and
# carry their own execution environment — declaring `code_execution` alongside
# them gives the model two and confuses it.
SERVER_TOOLS: dict[str, dict[str, Any]] = {
    "web_search": {"type": "web_search_20260209", "name": "web_search"},
    "web_fetch": {"type": "web_fetch_20260209", "name": "web_fetch"},
}

# A paused turn is resumed rather than returned half-finished, but not forever:
# a tool that keeps pausing would otherwise bill indefinitely.
_MAX_PAUSE_RESUMES = 4


def _web_sources_from(response: Any) -> list[WebSource]:
    """Pull the pages a search actually returned out of the response.

    A server tool does not raise on failure: the call comes back 200 with an
    error object where the results would be. On success `content` is a list; on
    failure it is a single object, so the shape is what has to be checked.
    """
    found: list[WebSource] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        content = getattr(block, "content", None)
        if not isinstance(content, list):
            code = getattr(content, "error_code", None)
            log.info("web_search_failed", error_code=code)
            continue
        for result in content:
            url = getattr(result, "url", None)
            if url:
                found.append(WebSource(title=getattr(result, "title", "") or url, url=url))
    return found


def _classify(exc: anthropic.APIStatusError, action: str) -> ProviderError:
    """Distinguish a rejected credential from a failure worth retrying.

    A 429 here is ordinary rate limiting, which clears on its own; only an
    outright rejection of the key means the provider cannot serve until someone
    intervenes.
    """
    detail = f"Claude {action} failed ({exc.status_code})."
    if exc.status_code in (401, 403):
        return ProviderCredentialError(detail)
    return ProviderError(detail)


def _usage_from(raw: Any) -> Usage:
    return Usage(
        input_tokens=getattr(raw, "input_tokens", 0) or 0,
        output_tokens=getattr(raw, "output_tokens", 0) or 0,
        cached_input_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
    )


# Anthropic's structured-output schema validator accepts only a subset of JSON
# Schema and rejects these value-constraint keywords outright. They constrain
# values, not shape, and the caller re-validates the response against its own
# Pydantic model, so dropping them for the API request loses nothing.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
)


def _sanitize_schema(node: Any) -> Any:
    """Strip value-constraint keywords Anthropic structured outputs rejects."""
    if isinstance(node, dict):
        return {
            key: _sanitize_schema(value)
            for key, value in node.items()
            if key not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(node, list):
        return [_sanitize_schema(item) for item in node]
    return node


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, *, timeout: float = 120.0) -> None:
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not configured.")
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)

    def models(self) -> list[ModelSpec]:
        return CLAUDE_MODELS

    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        model: str = DEFAULT_MODEL,
        system: str | None = None,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
        server_tools: list[str] | None = None,
    ) -> CompletionResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if json_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": _sanitize_schema(json_schema)}
            }

        tools = [SERVER_TOOLS[name] for name in (server_tools or []) if name in SERVER_TOOLS]
        if tools:
            kwargs["tools"] = tools

        started = time.perf_counter()
        history = list(kwargs["messages"])
        sources: list[WebSource] = []
        try:
            for _ in range(_MAX_PAUSE_RESUMES + 1):
                kwargs["messages"] = history
                if max_tokens > _STREAM_THRESHOLD_TOKENS:
                    async with self._client.messages.stream(**kwargs) as stream:
                        response = await stream.get_final_message()
                else:
                    response = await self._client.messages.create(**kwargs)

                sources.extend(_web_sources_from(response))
                # A server tool that runs long stops the turn with `pause_turn`
                # rather than an error. Returning here would hand back a
                # half-finished answer with nothing to say it was cut off, so
                # the paused turn is appended and the model asked to continue.
                if response.stop_reason != "pause_turn":
                    break
                history = [*history, {"role": "assistant", "content": response.content}]
        except anthropic.APIStatusError as exc:
            log.warning("anthropic_api_error", status=exc.status_code, model=model)
            raise _classify(exc, "request") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Could not reach the Claude API.") from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if response.stop_reason == "refusal":
            raise ProviderError("The model declined to answer this request.")

        text = "".join(b.text for b in response.content if b.type == "text")
        return CompletionResult(
            text=text,
            model=response.model,
            usage=_usage_from(response.usage),
            stop_reason=response.stop_reason,
            latency_ms=elapsed_ms,
            # Deduplicated by URL: the model often reads the same page across
            # several searches within one turn.
            web_sources=list({source.url: source for source in sources}.values()),
        )

    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        model: str = DEFAULT_MODEL,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(text=text)
                final = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            log.warning("anthropic_stream_error", status=exc.status_code, model=model)
            raise _classify(exc, "stream") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Could not reach the Claude API.") from exc

        yield StreamChunk(
            done=True,
            model=final.model,
            usage=_usage_from(final.usage),
            stop_reason=final.stop_reason,
        )

    async def health(self) -> bool:
        try:
            await self._client.models.list(limit=1)
        except Exception:
            return False
        return True
