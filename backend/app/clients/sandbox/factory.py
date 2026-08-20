"""Builds the configured sandbox, and the limits it must enforce."""

from __future__ import annotations

from app.clients.sandbox.base import Sandbox, SandboxLimits
from app.clients.sandbox.docker_sandbox import DockerSandbox
from app.clients.sandbox.http_sandbox import HttpSandbox
from app.core.config import Settings


def build_sandbox(settings: Settings) -> Sandbox | None:
    """Return the configured sandbox, or None when execution is disabled.

    There is intentionally no permissive fallback: if Docker is unavailable,
    analysis fails closed rather than running generated code with weaker
    isolation.
    """
    if settings.sandbox_backend == "disabled":
        return None
    if settings.sandbox_backend == "http":
        return HttpSandbox(settings.sandbox_url, settings.sandbox_auth_token or "")
    return DockerSandbox(settings.sandbox_image, work_root=settings.sandbox_work_root)


def build_limits(settings: Settings) -> SandboxLimits:
    return SandboxLimits(
        timeout_seconds=settings.sandbox_timeout_seconds,
        memory_mb=settings.sandbox_memory_mb,
        cpus=settings.sandbox_cpus,
        max_output_bytes=settings.sandbox_max_output_bytes,
        pids_limit=settings.sandbox_pids_limit,
        network=False,
    )
