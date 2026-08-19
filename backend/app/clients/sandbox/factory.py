"""Builds the configured sandbox, and the limits it must enforce."""

from __future__ import annotations

from app.clients.sandbox.base import Sandbox, SandboxLimits
from app.clients.sandbox.docker_sandbox import DockerSandbox
from app.core.config import Settings


def build_sandbox(settings: Settings) -> Sandbox | None:
    """Return the configured sandbox, or None when execution is disabled.

    There is intentionally no permissive fallback: if Docker is unavailable,
    analysis fails closed rather than running generated code with weaker
    isolation.
    """
    if settings.sandbox_backend == "disabled":
        return None
    return DockerSandbox(settings.sandbox_image)


def build_limits(settings: Settings) -> SandboxLimits:
    return SandboxLimits(
        timeout_seconds=settings.sandbox_timeout_seconds,
        memory_mb=settings.sandbox_memory_mb,
        cpus=settings.sandbox_cpus,
        max_output_bytes=settings.sandbox_max_output_bytes,
        pids_limit=settings.sandbox_pids_limit,
        network=False,
    )
