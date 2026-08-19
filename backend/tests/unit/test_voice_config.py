"""Voice configuration and provider-registry availability."""

from __future__ import annotations

import pytest

from app.clients.llm.router import ModelRouter, ProviderRegistry, TaskType
from app.clients.stt.factory import build_transcription_client
from app.core.config import Settings
from app.core.errors import ProviderError
from tests.fakes import FakeLLMProvider


def test_voice_is_off_by_default():
    settings = Settings(app_env="test")
    assert settings.voice_enabled is False
    assert build_transcription_client(settings) is None


def test_voice_needs_both_the_provider_and_the_key():
    # Selected but unconfigured is a boot-time error, not a silent no-op.
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
        Settings(app_env="test", stt_provider="deepgram")

    # A key without selecting the provider leaves voice off.
    settings = Settings(app_env="test", deepgram_api_key="k")
    assert settings.voice_enabled is False
    assert build_transcription_client(settings) is None


def test_voice_enabled_builds_a_client():
    settings = Settings(app_env="test", stt_provider="deepgram", deepgram_api_key="k")
    assert settings.voice_enabled is True
    client = build_transcription_client(settings)
    assert client is not None
    assert client.name == "deepgram"


def test_audio_limits_are_separate_from_document_limits():
    """Recordings are far larger than documents and get their own ceiling."""
    settings = Settings(app_env="test", max_upload_mb=25, max_audio_mb=100)
    assert settings.max_audio_bytes == 100 * 1024 * 1024
    assert settings.max_audio_bytes > settings.max_upload_bytes


def test_stream_duration_is_bounded():
    with pytest.raises(ValueError):
        Settings(app_env="test", voice_stream_max_seconds=100_000)


def test_an_unreachable_provider_can_be_excluded_from_the_catalogue():
    """Ollama needs no credential, so only probing it reveals whether it is
    actually usable. Reporting it as available when it is not makes GET /models
    lie."""
    registry = ProviderRegistry(Settings(app_env="test"))
    assert any(p.name == "ollama" for p in registry.available())

    registry.mark_unavailable("ollama")
    assert not any(p.name == "ollama" for p in registry.available())


def test_marking_unavailable_does_not_affect_a_registered_provider():
    registry = ProviderRegistry(Settings(app_env="test"))
    registry.register(FakeLLMProvider(), make_default=True)
    registry.mark_unavailable("ollama")

    # The registered double still routes normally.
    _, spec = ModelRouter(registry).resolve(task=TaskType.SYNTHESIS)
    assert spec.provider == "fake"


def test_registering_a_provider_clears_a_previous_exclusion():
    registry = ProviderRegistry(Settings(app_env="test"))
    registry.mark_unavailable("fake")
    registry.register(FakeLLMProvider())
    assert any(p.name == "fake" for p in registry.available())


def test_routing_fails_clearly_when_every_provider_was_excluded():
    registry = ProviderRegistry(Settings(app_env="test"))
    for name in ("anthropic", "openai", "ollama"):
        registry.mark_unavailable(name)
    with pytest.raises(ProviderError, match="No LLM provider is configured"):
        ModelRouter(registry).resolve(task=TaskType.SYNTHESIS)
