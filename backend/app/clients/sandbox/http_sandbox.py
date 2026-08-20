"""Sandbox client that delegates to the runner service.

The deployed counterpart of `DockerSandbox`. The API no longer needs the Docker
socket — and so no longer has root on its host — because a separate service
owns it.

Deliberately *not* sent: the limits. Those are the runner's to decide, from its
own configuration. A client that could name its own timeout and memory ceiling
could name unlimited ones, and putting the sandbox behind an API would have
weakened it rather than contained it.
"""

from __future__ import annotations

import base64
import time

import httpx

from app.clients.sandbox.base import Sandbox, SandboxDataset, SandboxLimits, SandboxResult
from app.core.logging import get_logger

log = get_logger(__name__)


class HttpSandbox(Sandbox):
    name = "http"

    def __init__(self, base_url: str, auth_token: str, *, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout = timeout

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self._base_url}/health")
                response.raise_for_status()
                return bool(response.json().get("docker_available"))
        except (httpx.HTTPError, ValueError):
            return False

    async def run(
        self, *, code: str, datasets: list[SandboxDataset], limits: SandboxLimits
    ) -> SandboxResult:
        started = time.perf_counter()
        payload = {
            "code": code,
            "datasets": [
                {
                    "variable": d.variable,
                    "filename": d.filename,
                    "content_b64": base64.b64encode(d.content).decode(),
                }
                for d in datasets
            ],
        }

        # The client's own deadline sits above the runner's, so a runner that
        # stops responding cannot hang the request indefinitely.
        request_timeout = max(self._timeout, limits.timeout_seconds + 30)

        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                response = await client.post(
                    f"{self._base_url}/run",
                    json=payload,
                    headers={"X-Sandbox-Token": self._auth_token},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            log.warning("sandbox_service_error", status=exc.response.status_code)
            return SandboxResult(
                success=False,
                error=f"The analysis sandbox refused the request ({exc.response.status_code}).",
                execution_ms=int((time.perf_counter() - started) * 1000),
            )
        except httpx.HTTPError:
            log.warning("sandbox_service_unreachable", url=self._base_url)
            return SandboxResult(
                success=False,
                error="The analysis sandbox is unreachable.",
                execution_ms=int((time.perf_counter() - started) * 1000),
            )

        return SandboxResult(
            success=bool(body.get("success")),
            stdout=body.get("stdout", ""),
            stderr=body.get("stderr", ""),
            error=body.get("error"),
            timed_out=bool(body.get("timed_out")),
            tables=body.get("tables", []),
            scalars=body.get("scalars", {}),
            chart_png_b64=body.get("chart_png_b64"),
            execution_ms=body.get("execution_ms") or int((time.perf_counter() - started) * 1000),
        )
