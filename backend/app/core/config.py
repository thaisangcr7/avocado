"""12-factor configuration.

Every environment-dependent value is read from the environment, so the same
image runs unchanged locally and in the cloud. Nothing here has a real
credential as a default — placeholders are rejected outside development so a
forgotten `.env` edit fails at boot instead of shipping a known secret.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER = "CHANGE_ME"

AppEnv = Literal["development", "test", "staging", "production"]
StorageBackend = Literal["local", "s3"]
EmbeddingProvider = Literal["voyage", "openai", "hash"]
SandboxBackend = Literal["docker", "disabled"]
SttProvider = Literal["deepgram", "disabled"]
LLMProviderName = Literal["anthropic", "openai", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App -----------------------------------------------------------
    app_env: AppEnv = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # --- Security ------------------------------------------------------
    secret_key: str = PLACEHOLDER
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14

    # --- Database ------------------------------------------------------
    database_url: str = "postgresql+asyncpg://avocado:avocado@localhost:5434/avocado"
    # What *migrations* connect with. The application should connect as a
    # restricted role that cannot bypass row-level security, while Alembic
    # needs owner rights to alter tables. Falls back to database_url so a
    # development machine works with one connection string.
    database_admin_url: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- Redis ---------------------------------------------------------
    redis_url: str = "redis://localhost:6380/0"

    # --- Storage -------------------------------------------------------
    storage_backend: StorageBackend = "local"
    storage_local_path: str = "./.localstorage"
    s3_bucket: str = "avocado-documents"
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    # --- LLM -----------------------------------------------------------
    llm_provider: LLMProviderName = "anthropic"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- Embeddings ----------------------------------------------------
    embedding_provider: EmbeddingProvider = "hash"
    embedding_dim: int = 1024
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-3"
    openai_embedding_model: str = "text-embedding-3-small"

    # --- Analysis sandbox ----------------------------------------------
    # These are hard security limits, not tuning knobs. See §13 of the
    # architecture doc: no network, hard timeout, resource caps — every path.
    sandbox_backend: SandboxBackend = "docker"
    sandbox_image: str = "avocado-sandbox:latest"
    sandbox_timeout_seconds: int = Field(default=30, ge=1, le=120)
    sandbox_memory_mb: int = Field(default=512, ge=64, le=4096)
    sandbox_cpus: float = Field(default=1.0, gt=0, le=4.0)
    sandbox_max_output_bytes: int = Field(default=1_048_576, ge=1024)
    sandbox_pids_limit: int = 128

    # --- Speech to text ------------------------------------------------
    stt_provider: SttProvider = "disabled"
    deepgram_api_key: str | None = None
    deepgram_model: str = "nova-2"
    # Recordings are far larger than documents, so they get their own ceiling.
    max_audio_mb: int = Field(default=100, ge=1, le=1000)
    # A live socket that is never closed by the client would otherwise hold a
    # provider connection open indefinitely.
    voice_stream_max_seconds: int = Field(default=300, ge=10, le=3600)

    # --- Uploads -------------------------------------------------------
    max_upload_mb: int = Field(default=25, ge=1, le=500)

    # --- Rate limiting -------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    # An organization is many people, so its allowance is correspondingly
    # larger than a single anonymous client's.
    rate_limit_org_requests: int = 1200
    rate_limit_window_seconds: int = 60

    # --- Public URLs ---------------------------------------------------
    # Where the web app is reachable. Invitation links are built from this, so
    # it has to be the address a recipient can actually open — not the API's.
    public_web_url: str = "http://localhost:5173"

    # --- CORS ----------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def migration_url(self) -> str:
        return self.database_admin_url or self.database_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_mb * 1024 * 1024

    @property
    def voice_enabled(self) -> bool:
        return self.stt_provider != "disabled" and bool(self.deepgram_api_key)

    @property
    def is_production(self) -> bool:
        return self.app_env in ("staging", "production")

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _reject_placeholders(self) -> Settings:
        """Fail fast rather than boot with a known-public secret."""
        if self.secret_key == PLACEHOLDER or not self.secret_key:
            if self.is_production:
                raise ValueError(
                    "SECRET_KEY is unset or still the placeholder. Generate one with "
                    '`python -c "import secrets; print(secrets.token_urlsafe(48))"`.'
                )
            # Dev/test: a per-process random key. Tokens do not survive a
            # restart, which is correct — it makes the missing config obvious
            # without blocking local work.
            self.secret_key = secrets.token_urlsafe(48)

        if self.is_production:
            if self.storage_backend == "local":
                raise ValueError("STORAGE_BACKEND=local is not permitted outside development.")
            if self.embedding_provider == "hash":
                raise ValueError(
                    "EMBEDDING_PROVIDER=hash produces meaningless vectors and is "
                    "development-only. Configure voyage or openai."
                )
            if self.debug:
                raise ValueError("DEBUG must be false in staging/production.")
        return self

    @model_validator(mode="after")
    def _require_provider_keys(self) -> Settings:
        """A selected provider without its credential is a boot-time error."""
        if self.embedding_provider == "voyage" and not self.voyage_api_key:
            raise ValueError("EMBEDDING_PROVIDER=voyage requires VOYAGE_API_KEY.")
        if self.embedding_provider == "openai" and not self.openai_api_key:
            raise ValueError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        if self.stt_provider == "deepgram" and not self.deepgram_api_key:
            raise ValueError("STT_PROVIDER=deepgram requires DEEPGRAM_API_KEY.")
        if self.storage_backend == "s3" and not (
            self.s3_access_key_id and self.s3_secret_access_key
        ):
            raise ValueError(
                "STORAGE_BACKEND=s3 requires S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
