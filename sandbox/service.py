"""The sandbox runner: a service whose only job is executing analysis code.

Local development mounts the Docker socket into the API container so it can
start sandbox containers as siblings. That grants the API control of the host
daemon — effectively root on the host — which is fine on a laptop and
unacceptable anywhere else.

So the socket belongs to *this* process instead. It is deliberately tiny: one
endpoint, no database, no model access, no tenant data beyond the rows it is
handed for a single run. Compromising the API no longer means owning the host;
it means being able to ask this service to run sandboxed code, which is what
the API is allowed to do anyway.

**Limits come from this service's own configuration, never from the request.**
A caller that could specify its own timeout and memory ceiling could ask for
unlimited ones, and moving the sandbox behind an API would have weakened it
rather than contained it.
"""

from __future__ import annotations

import base64
import os
import secrets
import sys

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/backend")

from app.clients.sandbox.base import SandboxDataset, SandboxLimits  # noqa: E402
from app.clients.sandbox.docker_sandbox import DockerSandbox  # noqa: E402

IMAGE = os.environ.get("SANDBOX_IMAGE", "avocado-sandbox:latest")

# The limits this service will enforce, from its own environment.
LIMITS = SandboxLimits(
    timeout_seconds=int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "30")),
    memory_mb=int(os.environ.get("SANDBOX_MEMORY_MB", "512")),
    cpus=float(os.environ.get("SANDBOX_CPUS", "1.0")),
    max_output_bytes=int(os.environ.get("SANDBOX_MAX_OUTPUT_BYTES", "1048576")),
    pids_limit=int(os.environ.get("SANDBOX_PIDS_LIMIT", "128")),
    network=False,
)

# Shared secret between the API and this service. Absent, the service refuses
# to start rather than accepting anonymous code execution.
AUTH_TOKEN = os.environ.get("SANDBOX_AUTH_TOKEN", "")

MAX_DATASET_BYTES = int(os.environ.get("SANDBOX_MAX_DATASET_BYTES", str(64 * 1024 * 1024)))

app = FastAPI(title="Avocado sandbox runner", docs_url=None, redoc_url=None)
# The per-run directory must live somewhere the *host* daemon can also see,
# because a bind mount source is resolved there, not here.
WORK_ROOT = os.environ.get("SANDBOX_WORK_ROOT") or None
_sandbox = DockerSandbox(IMAGE, work_root=WORK_ROOT)


class DatasetPayload(BaseModel):
    variable: str = Field(max_length=64)
    filename: str = Field(max_length=200)
    content_b64: str


class RunRequest(BaseModel):
    """What the API may ask for.

    Note what is *not* here: any limit. Those are this service's to decide.
    """

    code: str = Field(max_length=100_000)
    datasets: list[DatasetPayload] = Field(default_factory=list, max_length=8)


def _authorise(token: str | None) -> None:
    if not AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox runner is not configured with an auth token.",
        )
    # Constant-time: a token compared byte-by-byte leaks its prefix by timing.
    if not token or not secrets.compare_digest(token, AUTH_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorised.")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "image": IMAGE,
        "docker_available": await _sandbox.available(),
        "limits": {
            "timeout_seconds": LIMITS.timeout_seconds,
            "memory_mb": LIMITS.memory_mb,
            "cpus": LIMITS.cpus,
        },
    }


@app.post("/run")
async def run(payload: RunRequest, x_sandbox_token: str = Header(default="")) -> dict:
    _authorise(x_sandbox_token)

    if not await _sandbox.available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No container runtime is available.",
        )

    datasets = []
    total = 0
    for entry in payload.datasets:
        try:
            content = base64.b64decode(entry.content_b64, validate=True)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Dataset content is not valid base64.",
            ) from exc

        total += len(content)
        if total > MAX_DATASET_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Datasets exceed the sandbox size limit.",
            )
        # Path separators would let a filename escape the mounted directory.
        safe_name = os.path.basename(entry.filename) or "data.csv"
        datasets.append(
            SandboxDataset(variable=entry.variable, filename=safe_name, content=content)
        )

    result = await _sandbox.run(code=payload.code, datasets=datasets, limits=LIMITS)
    return {
        "success": result.success,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": result.error,
        "timed_out": result.timed_out,
        "execution_ms": result.execution_ms,
        "tables": result.tables,
        "scalars": result.scalars,
        "chart_png_b64": result.chart_png_b64,
    }
