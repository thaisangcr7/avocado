"""Provider registry and the Auto-mode model router.

Two responsibilities, kept together because they are the same decision seen
from different angles:

* **Registry** — build and cache one adapter per configured vendor. Adapters
  are constructed lazily so a missing OpenAI key doesn't stop the app booting
  when only Claude is in use.
* **Router** — resolve a request to a concrete model. A workspace pinned to a
  model always gets that model. A workspace on Auto gets a model chosen by task
  type: cheap and fast for classification and titling, the strongest available
  for analysis code generation and final synthesis.

The chosen model id always travels back to the caller and is persisted on the
message, so a user on Auto can see which model actually answered.
"""

from __future__ import annotations

from enum import StrEnum

from app.clients.llm.anthropic_provider import AnthropicProvider
from app.clients.llm.base import LLMProvider, ModelSpec
from app.clients.llm.ollama_provider import OllamaProvider
from app.clients.llm.openai_provider import OpenAIProvider
from app.core.config import Settings
from app.core.errors import ProviderError, ValidationError
from app.core.logging import get_logger

log = get_logger(__name__)


class TaskType(StrEnum):
    """What a call is for. Determines model choice under Auto."""

    # Cheap, high-volume, low-judgement.
    CLASSIFICATION = "classification"
    TITLE = "title"
    RERANK = "rerank"
    # Quality-sensitive.
    SYNTHESIS = "synthesis"
    SUMMARIZATION = "summarization"
    VISION_EXTRACTION = "vision_extraction"
    # Correctness-critical: generated code will actually be executed.
    CODE_GENERATION = "code_generation"


# Which capability tier Auto should reach for, per task.
_TASK_TIER: dict[TaskType, str] = {
    TaskType.CLASSIFICATION: "fast",
    TaskType.TITLE: "fast",
    TaskType.RERANK: "fast",
    TaskType.SUMMARIZATION: "balanced",
    TaskType.SYNTHESIS: "frontier",
    TaskType.VISION_EXTRACTION: "frontier",
    TaskType.CODE_GENERATION: "frontier",
}

_TIER_FALLBACK: dict[str, list[str]] = {
    "fast": ["fast", "balanced", "frontier"],
    "balanced": ["balanced", "frontier", "fast"],
    "frontier": ["frontier", "balanced", "fast"],
}


class ProviderRegistry:
    """Lazily constructs and caches one adapter per vendor."""

    def __init__(self, settings: Settings, *, default_provider: str | None = None) -> None:
        self._settings = settings
        self._default_provider = default_provider or settings.llm_provider
        self._cache: dict[str, LLMProvider] = {}
        # Providers registered explicitly rather than built from configuration.
        # This is the seam tests use to inject a double, and the seam a future
        # provider added at runtime would use — either way it beats reaching
        # into the cache from outside.
        self._registered: dict[str, LLMProvider] = {}

    @property
    def default_provider_name(self) -> str:
        return self._default_provider

    def register(self, provider: LLMProvider, *, make_default: bool = False) -> None:
        """Add a ready-made provider, bypassing credential-based construction."""
        self._registered[provider.name] = provider
        self._cache[provider.name] = provider
        if make_default:
            self._default_provider = provider.name

    def get(self, name: str | None = None) -> LLMProvider:
        name = name or self.default_provider_name
        if name in self._cache:
            return self._cache[name]

        s = self._settings
        if name == "anthropic":
            provider: LLMProvider = AnthropicProvider(s.anthropic_api_key)
        elif name == "openai":
            provider = OpenAIProvider(s.openai_api_key)
        elif name == "ollama":
            provider = OllamaProvider(s.ollama_base_url)
        else:
            raise ValidationError(f"Unknown LLM provider '{name}'.")

        self._cache[name] = provider
        return provider

    def available(self) -> list[LLMProvider]:
        """Every provider that is actually configured.

        A provider whose credential is missing is skipped rather than raising,
        so `GET /models` degrades to "what you can actually use" instead of
        failing outright.
        """
        # An explicitly registered provider is available by definition — its
        # construction already succeeded.
        out: list[LLMProvider] = list(self._registered.values())
        for name in ("anthropic", "openai", "ollama"):
            if name in self._registered:
                continue
            if name == "anthropic" and not self._settings.anthropic_api_key:
                continue
            if name == "openai" and not self._settings.openai_api_key:
                continue
            try:
                out.append(self.get(name))
            except ProviderError:
                continue
        return out

    def all_models(self) -> list[ModelSpec]:
        return [spec for provider in self.available() for spec in provider.models()]

    def find_model(self, model_id: str) -> tuple[LLMProvider, ModelSpec]:
        for provider in self.available():
            spec = provider.spec_for(model_id)
            if spec:
                return provider, spec
        raise ValidationError(f"Model '{model_id}' is not available.")


class ModelRouter:
    """Resolves (workspace preference, task type) to a concrete model."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def resolve(
        self, *, task: TaskType, preferred_model: str | None = None
    ) -> tuple[LLMProvider, ModelSpec]:
        # A pinned model wins unconditionally — that is the contract the model
        # picker makes with the user.
        if preferred_model:
            return self._registry.find_model(preferred_model)

        models = self._registry.all_models()
        if not models:
            raise ProviderError(
                "No LLM provider is configured. Set ANTHROPIC_API_KEY (or another "
                "provider's key) to enable generation."
            )

        wanted_tier = _TASK_TIER[task]
        for tier in _TIER_FALLBACK[wanted_tier]:
            # Within a tier, prefer the default provider, then cheapest input.
            candidates = sorted(
                (m for m in models if m.tier == tier),
                key=lambda m: (
                    m.provider != self._registry.default_provider_name,
                    m.input_cost_per_mtok,
                ),
            )
            if candidates:
                spec = candidates[0]
                provider, _ = self._registry.find_model(spec.id)
                log.debug("model_routed", task=task.value, model=spec.id, tier=tier)
                return provider, spec

        raise ProviderError("No model satisfies the requested capability tier.")
