"""Auto-mode routing and provider selection."""

from __future__ import annotations

import pytest

from app.clients.llm.router import ModelRouter, ProviderRegistry, TaskType
from app.core.config import Settings
from app.core.errors import ProviderError, ValidationError
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
