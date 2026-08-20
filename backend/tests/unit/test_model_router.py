"""Auto-mode routing and provider selection."""

from __future__ import annotations

import httpx
import openai
import pytest

from app.clients.llm.openai_provider import _classify as _openai_classify
from app.clients.llm.router import (
    BudgetState,
    ModelRouter,
    ProviderRegistry,
    TaskType,
    _HealthTracked,
)
from app.core.config import Settings
from app.core.errors import (
    BudgetExceededError,
    ProviderCredentialError,
    ProviderError,
    ValidationError,
)
from tests.fakes import FakeLLMProvider


@pytest.fixture
def registry() -> ProviderRegistry:
    registry = ProviderRegistry(Settings(app_env="test"))
    registry.register(FakeLLMProvider(), make_default=True)
    return registry


def test_a_pinned_model_always_wins(registry):
    router = ModelRouter(registry)
    # Even for a task Auto would route to the frontier tier.
    _, spec = router.resolve(task=TaskType.CODE_GENERATION, preferred_model="fake-fast")
    assert spec.id == "fake-fast"


def test_auto_sends_cheap_tasks_to_a_fast_model(registry):
    router = ModelRouter(registry)
    for task in (TaskType.TITLE, TaskType.CLASSIFICATION, TaskType.RERANK):
        _, spec = router.resolve(task=task)
        assert spec.tier == "fast", task


def test_auto_sends_quality_critical_tasks_to_the_strongest_model(registry):
    router = ModelRouter(registry)
    for task in (TaskType.CODE_GENERATION, TaskType.SYNTHESIS, TaskType.VISION_EXTRACTION):
        _, spec = router.resolve(task=task)
        assert spec.tier == "frontier", task


def test_unknown_pinned_model_is_rejected(registry):
    with pytest.raises(ValidationError):
        ModelRouter(registry).resolve(task=TaskType.SYNTHESIS, preferred_model="gpt-9")


def test_routing_without_any_provider_fails_clearly():
    # No provider registered and no credential configured.
    empty = ProviderRegistry(Settings(app_env="test"))
    with pytest.raises(ProviderError, match="No LLM provider is configured"):
        ModelRouter(empty).resolve(task=TaskType.SYNTHESIS)


def test_cost_is_computed_from_the_model_spec(registry):
    from app.clients.llm.base import Usage

    _, spec = registry.find_model("fake-frontier")
    # 1M input at $5 + 1M output at $25.
    assert spec.cost_usd(Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == 30.0


class _FailingProvider(FakeLLMProvider):
    """A fake that always fails a generate call with a given error."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def generate(self, **kwargs):
        raise self._error


async def _drive(registry, provider_name, error):
    """Route one generate call through the registry's tracking wrapper."""
    tracked = _HealthTracked(_FailingProvider(error), registry)
    with pytest.raises(type(error)):
        await tracked.generate(messages=[], model="fake-fast")
    return tracked


@pytest.mark.anyio
async def test_a_rejected_credential_retires_the_provider():
    registry = ProviderRegistry(Settings(app_env="test"))
    registry.register(FakeLLMProvider(), make_default=True)
    assert "fake" in [p.name for p in registry.available()]
    await _drive(registry, "fake", ProviderCredentialError("quota exhausted"))
    assert "fake" not in [
        p.name for p in registry.available()
    ], "a retired provider must stop being offered"


@pytest.mark.anyio
async def test_an_ordinary_rate_limit_does_not_retire_the_provider():
    """A burst of 429s must not disable a provider for everyone.

    This is the failure mode that makes naive health tracking worse than none:
    treating transient throttling as permanent turns a slow minute into an
    outage that lasts until someone restarts the process.
    """
    registry = ProviderRegistry(Settings(app_env="test"))
    registry.register(FakeLLMProvider(), make_default=True)
    await _drive(registry, "fake", ProviderError("rate limited (429)"))
    assert "fake" in [p.name for p in registry.available()]


def test_openai_classifies_quota_exhaustion_as_a_credential_failure():
    exc = openai.APIStatusError(
        "quota",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
        body={"error": {"code": "insufficient_quota"}},
    )
    assert isinstance(_openai_classify(exc), ProviderCredentialError)


def test_openai_treats_a_plain_rate_limit_as_transient():
    exc = openai.APIStatusError(
        "slow down",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
        body={"error": {"code": "rate_limit_exceeded"}},
    )
    classified = _openai_classify(exc)
    assert isinstance(classified, ProviderError)
    assert not isinstance(classified, ProviderCredentialError)


def test_openai_treats_a_revoked_key_as_a_credential_failure():
    exc = openai.APIStatusError(
        "bad key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com")),
        body={"error": {"code": "invalid_api_key"}},
    )
    assert isinstance(_openai_classify(exc), ProviderCredentialError)


# --- budget-aware routing --------------------------------------------------


def test_an_exhausted_budget_refuses_even_a_pinned_model(registry):
    """A ceiling the model picker can opt out of is not a ceiling."""
    router = ModelRouter(registry, budget=BudgetState.EXHAUSTED)
    with pytest.raises(BudgetExceededError):
        router.resolve(task=TaskType.SYNTHESIS, preferred_model="fake-fast")
    with pytest.raises(BudgetExceededError):
        router.resolve(task=TaskType.SYNTHESIS)


def test_a_constrained_budget_downgrades_auto_off_the_frontier(registry):
    frontier = ModelRouter(registry).resolve(task=TaskType.SYNTHESIS)[1]
    assert frontier.tier == "frontier"

    constrained = ModelRouter(registry, budget=BudgetState.CONSTRAINED)
    _, spec = constrained.resolve(task=TaskType.SYNTHESIS)
    assert spec.tier != "frontier", "a constrained budget should stop reaching for the top tier"


def test_a_constrained_budget_still_honours_an_explicit_pin(registry):
    """Constrained is a hint to Auto, not an override of a deliberate choice.

    The user is under the ceiling and has said which model they want; silently
    serving a different one would misreport what answered.
    """
    router = ModelRouter(registry, budget=BudgetState.CONSTRAINED)
    _, spec = router.resolve(task=TaskType.SYNTHESIS, preferred_model="fake-frontier")
    assert spec.id == "fake-frontier"


def test_a_constrained_budget_leaves_cheap_tasks_alone(registry):
    router = ModelRouter(registry, budget=BudgetState.CONSTRAINED)
    _, spec = router.resolve(task=TaskType.TITLE)
    assert spec.tier == "fast"


def test_budget_defaults_to_unconstrained(registry):
    """Background work has no request to read a budget from."""
    _, spec = ModelRouter(registry).resolve(task=TaskType.SYNTHESIS)
    assert spec.tier == "frontier"
