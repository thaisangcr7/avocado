"""The one interface every LLM provider implements.

Services depend on `LLMProvider`, never on a vendor SDK. Each vendor streams
and reports usage differently; normalising that here is the whole point —
`ChatService` should not know that Anthropic reports cache reads separately or
that Ollama reports no cost at all.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


@dataclass(slots=True)
class ImagePart:
    """An inline image for a multimodal turn."""

    media_type: str
    data_b64: str


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str
    images: list[ImagePart] = field(default_factory=list)


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class WebSource:
    """A page the model consulted through a server-side search."""

    title: str
    url: str


@dataclass(slots=True)
class CompletionResult:
    text: str
    model: str
    usage: Usage
    stop_reason: str | None = None
    latency_ms: int = 0
    raw: dict[str, Any] | None = None
    # Pages a server-side search actually returned. Kept separate from the
    # document citations a workspace answer carries: one is the team's own
    # material, the other is the open web, and a reader has to be able to tell
    # which a claim rests on.
    web_sources: list[WebSource] = field(default_factory=list)


@dataclass(slots=True)
class StreamChunk:
    """One increment of a streamed response.

    A terminal chunk carries `done=True` plus the final usage, so a consumer
    can log cost without a second round trip.
    """

    text: str = ""
    done: bool = False
    model: str | None = None
    usage: Usage | None = None
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """What a model is and what it costs, for the router and the usage log."""

    id: str
    provider: str
    display_name: str
    context_window: int
    max_output_tokens: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    supports_vision: bool = True
    tier: Literal["fast", "balanced", "frontier"] = "balanced"

    def cost_usd(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self.input_cost_per_mtok
            + usage.output_tokens * self.output_cost_per_mtok
        ) / 1_000_000


class LLMProvider(abc.ABC):
    """Adapter contract. One implementation per vendor, under `clients/llm/`."""

    name: str

    # Server-side tools this vendor hosts. Declared by the adapter rather than
    # inferred from its name, so asking "can this run a web search" is a
    # question about capability and not about string-matching a vendor.
    server_tools: frozenset[str] = frozenset()

    @abc.abstractmethod
    def models(self) -> list[ModelSpec]:
        """Models this provider can serve, in preference order."""

    @abc.abstractmethod
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
        """Single-shot completion.

        `json_schema` constrains the output shape. `server_tools` names
        provider-hosted tools to offer — a provider that has none simply
        ignores them, so a caller never has to ask who it is talking to.
        """

    @abc.abstractmethod
    def stream(
        self,
        *,
        messages: list[ChatMessage],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Token-by-token completion, terminated by a chunk with `done=True`."""

    async def health(self) -> bool:
        """Cheap reachability probe. Overridden where a real check is possible."""
        return True

    def spec_for(self, model: str) -> ModelSpec | None:
        return next((m for m in self.models() if m.id == model), None)
