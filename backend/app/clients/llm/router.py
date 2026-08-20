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

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

from app.clients.llm.anthropic_provider import AnthropicProvider
from app.clients.llm.base import CompletionResult, LLMProvider, ModelSpec, StreamChunk
from app.clients.llm.ollama_provider import OllamaProvider
from app.clients.llm.openai_provider import OpenAIProvider
from app.core.config import Settings
from app.core.errors import (
    BudgetExceededError,
    ProviderCredentialError,
    ProviderError,
    ValidationError,
)
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


class BudgetState(StrEnum):
    """How much of an organization's monthly ceiling is already spent.

    Computed by the service layer, which has the database; consumed by the
    router, which stays pure so the policy is testable without one.
    """

    OK = "ok"
    # Past the soft threshold: keep serving, but stop reaching for the
    # expensive tier on Auto.
    CONSTRAINED = "constrained"
    # At or past the ceiling. Nothing bills further until the month rolls over
    # or someone raises the budget.
    EXHAUSTED = "exhausted"


# Fraction of the ceiling at which Auto stops choosing frontier models. Chosen
# so the constrained window is wide enough to notice and act on before spend
# actually stops.
BUDGET_SOFT_THRESHOLD = 0.8


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


class _HealthTracked(LLMProvider):
    """Delegates to a real provider, and retires it when its credential fails.

    A provider whose key is revoked or whose account is out of quota keeps
    accepting requests and keeps failing them, so Auto mode would route real
    traffic into a guaranteed error and `GET /models` would advertise models
    nobody can call. Watching the calls that actually happen is the only way to
    see it: an exhausted quota is invisible to a startup probe, because listing
    models still succeeds when completions do not.

    Only `ProviderCredentialError` retires a provider. Ordinary rate limits and
    upstream blips stay transient by design.
    """

    def __init__(self, inner: LLMProvider, registry: ProviderRegistry) -> None:
        self._inner = inner
        self._registry = registry
        self.name = inner.name

    def models(self) -> list[ModelSpec]:
        return self._inner.models()

    def spec_for(self, model: str) -> ModelSpec | None:
        return self._inner.spec_for(model)

    async def health(self) -> bool:
        return await self._inner.health()

    def _retire(self, exc: ProviderCredentialError) -> None:
        log.warning("provider_retired", provider=self.name, detail=exc.detail)
        self._registry.mark_unavailable(self.name)

    async def generate(self, **kwargs: Any) -> CompletionResult:
        try:
            return await self._inner.generate(**kwargs)
        except ProviderCredentialError as exc:
            self._retire(exc)
            raise

    async def stream(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        try:
            async for chunk in self._inner.stream(**kwargs):
                yield chunk
        except ProviderCredentialError as exc:
            self._retire(exc)
            raise


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
        # Providers that failed a startup probe. Ollama needs no credential, so
        # configuration alone cannot tell us whether it is actually reachable;
        # only asking it can.
        self._unavailable: set[str] = set()

    @property
    def default_provider_name(self) -> str:
        return self._default_provider

    def register(self, provider: LLMProvider, *, make_default: bool = False) -> None:
        """Add a ready-made provider, bypassing credential-based construction."""
        self._registered[provider.name] = provider
        self._cache[provider.name] = provider
        self._unavailable.discard(provider.name)
        if make_default:
            self._default_provider = provider.name

    def mark_unavailable(self, name: str) -> None:
        """Exclude a provider that failed its startup probe.

        Reporting a provider as available when it cannot serve a request makes
        `GET /models` and the readiness check lie, which is worse than offering
        one fewer option.
        """
        self._unavailable.add(name)

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

        # Wrapped so a rejected credential retires the provider instead of
        # failing every request that reaches it. Explicitly registered
        # providers are left alone: a test double is the caller's to control.
        tracked = _HealthTracked(provider, self)
        self._cache[name] = tracked
        return tracked

    def available(self) -> list[LLMProvider]:
        """Every provider that is actually configured.

        A provider whose credential is missing is skipped rather than raising,
        so `GET /models` degrades to "what you can actually use" instead of
        failing outright.
        """
        # Registering a provider asserts it works, and `register` clears any
        # earlier exclusion. It can still be retired afterwards, though, so the
        # exclusion set is applied uniformly rather than only to the providers
        # built from configuration.
        out: list[LLMProvider] = [
            provider for name, provider in self._registered.items() if name not in self._unavailable
        ]
        for name in ("anthropic", "openai", "ollama"):
            if name in self._registered or name in self._unavailable:
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

    def __init__(self, registry: ProviderRegistry, *, budget: BudgetState = BudgetState.OK) -> None:
        self._registry = registry
        # Bound at construction so background work, which has no request to
        # read a budget from, defaults to unconstrained rather than guessing.
        self._budget = budget

    def resolve(
        self,
        *,
        task: TaskType,
        preferred_model: str | None = None,
        budget: BudgetState | None = None,
    ) -> tuple[LLMProvider, ModelSpec]:
        budget = budget if budget is not None else self._budget
        # An exhausted budget stops everything, including a pinned model. A
        # ceiling that the model picker can opt out of is not a ceiling.
        if budget is BudgetState.EXHAUSTED:
            raise BudgetExceededError(
                "This organization has reached its monthly spend limit. Raise the "
                "limit or wait for the next billing month."
            )

        # Otherwise a pinned model wins unconditionally — that is the contract
        # the model picker makes with the user. Being merely constrained does
        # not override an explicit choice; it only changes what Auto picks.
        if preferred_model:
            return self._registry.find_model(preferred_model)

        models = self._registry.all_models()
        if not models:
            raise ProviderError(
                "No LLM provider is configured. Set ANTHROPIC_API_KEY (or another "
                "provider's key) to enable generation."
            )

        wanted_tier = _TASK_TIER[task]
        tier_order = _TIER_FALLBACK[wanted_tier]
        if budget is BudgetState.CONSTRAINED and wanted_tier == "frontier":
            # Downgrade rather than refuse: a cheaper answer beats no answer,
            # and the spend curve flattens before the ceiling is hit. Frontier
            # stays last rather than being dropped, so an organization whose
            # only configured models are frontier still gets served instead of
            # silently losing generation at 80% of budget.
            tier_order = ["balanced", "fast", "frontier"]
            log.info("model_downgraded_for_budget", task=task.value, from_tier=wanted_tier)

        for tier in tier_order:
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
