"""Every provider really implements the interface it claims to.

An abstract method does not check its own signature: a subclass that omits a
parameter still satisfies `LLMProvider`, imports cleanly, and passes every test
that happens to use a different provider. It fails at runtime, on the one
workspace pinned to that vendor, with a TypeError rather than anything
diagnostic.

That is not hypothetical — adding `server_tools` for web search left the OpenAI
and Ollama adapters behind exactly this way.
"""

from __future__ import annotations

import inspect

import pytest

from app.clients.llm.anthropic_provider import AnthropicProvider
from app.clients.llm.base import LLMProvider
from app.clients.llm.ollama_provider import OllamaProvider
from app.clients.llm.openai_provider import OpenAIProvider
from tests.fakes import FakeLLMProvider

IMPLEMENTATIONS = [AnthropicProvider, OpenAIProvider, OllamaProvider, FakeLLMProvider]


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS, ids=lambda i: i.__name__)
def test_generate_accepts_every_parameter_the_contract_defines(implementation):
    contract = set(inspect.signature(LLMProvider.generate).parameters)
    implemented = set(inspect.signature(implementation.generate).parameters)

    missing = contract - implemented
    assert not missing, (
        f"{implementation.__name__}.generate is missing {sorted(missing)}. "
        "A caller that passes it gets a TypeError at runtime."
    )


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS, ids=lambda i: i.__name__)
def test_every_contract_parameter_is_keyword_only(implementation):
    """The contract is keyword-only, so a positional mismatch cannot silently
    bind the wrong argument to the wrong parameter."""
    parameters = inspect.signature(implementation.generate).parameters
    positional = [
        name
        for name, p in parameters.items()
        if name != "self" and p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    assert positional == [], f"{implementation.__name__}.generate takes {positional} positionally"


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS, ids=lambda i: i.__name__)
def test_the_fake_does_not_drift_from_the_real_thing(implementation):
    """A double with a wider signature hides the gap it exists to expose."""
    contract = set(inspect.signature(LLMProvider.generate).parameters)
    implemented = set(inspect.signature(implementation.generate).parameters)
    assert implemented <= contract, (
        f"{implementation.__name__}.generate accepts {sorted(implemented - contract)}, "
        "which the interface does not define."
    )


def test_the_health_wrapper_forwards_capabilities_it_does_not_own():
    """`_HealthTracked` wraps every provider built from configuration.

    It subclasses the interface, so any class attribute it forgets to forward
    silently answers with the base-class default instead of the real one. For
    `server_tools` that default is empty, which made web search report itself
    unavailable on the one vendor that hosts it — while every unit test passed,
    because they use an unwrapped double.
    """
    from app.clients.llm.router import ProviderRegistry, _HealthTracked
    from app.core.config import Settings

    registry = ProviderRegistry(Settings(app_env="test"))
    inner = AnthropicProvider("sk-not-a-real-key")
    wrapped = _HealthTracked(inner, registry)

    assert wrapped.server_tools == inner.server_tools
    assert "web_search" in wrapped.server_tools


def test_every_public_interface_attribute_survives_wrapping():
    """The specific attribute above is not the point; the pattern is."""
    from app.clients.llm.router import ProviderRegistry, _HealthTracked
    from app.core.config import Settings

    registry = ProviderRegistry(Settings(app_env="test"))
    inner = AnthropicProvider("sk-not-a-real-key")
    wrapped = _HealthTracked(inner, registry)

    declared = [
        name
        for name in vars(LLMProvider)
        if not name.startswith("_") and not callable(getattr(LLMProvider, name, None))
    ]
    for name in declared:
        assert getattr(wrapped, name) == getattr(inner, name), (
            f"_HealthTracked drops '{name}', so a wrapped provider reports the "
            "base-class default instead of its own."
        )
