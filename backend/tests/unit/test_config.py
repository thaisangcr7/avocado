"""Configuration guardrails."""

from __future__ import annotations

import pytest

from app.core.config import PLACEHOLDER, Settings


def test_development_generates_a_key_when_none_is_set():
    settings = Settings(app_env="development", secret_key=PLACEHOLDER)
    assert settings.secret_key != PLACEHOLDER
    assert len(settings.secret_key) > 30


def test_production_refuses_a_placeholder_secret():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            app_env="production",
            secret_key=PLACEHOLDER,
            storage_backend="s3",
            s3_access_key_id="k",
            s3_secret_access_key="s",
            embedding_provider="openai",
            openai_api_key="x",
        )


def test_production_refuses_local_storage():
    with pytest.raises(ValueError, match="STORAGE_BACKEND"):
        Settings(app_env="production", secret_key="k" * 48, storage_backend="local")


def test_production_refuses_the_hash_embedding_stand_in():
    """The hashing provider is not semantic; it must never serve production."""
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
        Settings(
            app_env="production",
            secret_key="k" * 48,
            storage_backend="s3",
            s3_access_key_id="k",
            s3_secret_access_key="s",
            embedding_provider="hash",
        )


def test_production_refuses_debug():
    with pytest.raises(ValueError, match="DEBUG"):
        Settings(
            app_env="production",
            secret_key="k" * 48,
            debug=True,
            storage_backend="s3",
            s3_access_key_id="k",
            s3_secret_access_key="s",
            embedding_provider="openai",
            openai_api_key="x",
        )


def test_selected_provider_without_its_key_fails_at_boot():
    with pytest.raises(ValueError, match="VOYAGE_API_KEY"):
        Settings(app_env="development", embedding_provider="voyage")
    with pytest.raises(ValueError, match="S3_ACCESS_KEY_ID"):
        Settings(app_env="development", storage_backend="s3")


def test_http_sandbox_requires_a_nonempty_token():
    with pytest.raises(ValueError, match="SANDBOX_AUTH_TOKEN"):
        Settings(app_env="development", sandbox_backend="http", sandbox_auth_token="   ")


def test_sandbox_limits_are_bounded():
    """Limits are security controls, so absurd values are rejected outright."""
    with pytest.raises(ValueError):
        Settings(app_env="development", sandbox_timeout_seconds=99999)
    with pytest.raises(ValueError):
        Settings(app_env="development", sandbox_memory_mb=1)


def test_cors_origins_parse_into_a_list():
    settings = Settings(app_env="development", cors_origins="http://a.com, http://b.com")
    assert settings.cors_origin_list == ["http://a.com", "http://b.com"]


def test_public_web_url_is_normalized_and_validated():
    settings = Settings(app_env="development", public_web_url="https://app.example.com/")
    assert settings.public_web_url == "https://app.example.com"


def test_public_web_url_rejects_paths():
    with pytest.raises(ValueError, match="PUBLIC_WEB_URL"):
        Settings(app_env="development", public_web_url="https://app.example.com/invite")


def test_cors_origins_reject_paths_and_non_http_urls():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(app_env="development", cors_origins="https://app.example.com/api")
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(app_env="development", cors_origins="ftp://app.example.com")
