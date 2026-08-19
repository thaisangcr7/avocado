"""Sandbox contract for executing model-generated analysis code.

Architecture §13 makes three guarantees non-negotiable on *every* execution
path: no network access, a hard timeout, and resource caps. The contract here
exists so those guarantees are a property of the interface rather than of one
implementation — an E2B-backed sandbox can be added later, but it has to
satisfy the same `SandboxLimits`.

There is deliberately no "just run it locally" implementation. When no
compliant sandbox is available the service raises
`SandboxUnavailableError` and the analysis fails closed.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    timeout_seconds: int
    memory_mb: int
    cpus: float
    max_output_bytes: int
    pids_limit: int = 128
    network: bool = False  # Never True. Present so the guarantee is explicit.


@dataclass(slots=True)
class SandboxDataset:
    """One table made available to the executed code.

    `variable` is the pandas DataFrame name the code will refer to.
    """

    variable: str
    filename: str
    content: bytes


@dataclass(slots=True)
class SandboxResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    timed_out: bool = False
    execution_ms: int = 0
    # Structured values the runner extracted: printed tables, scalars, chart.
    tables: list[dict[str, Any]] = field(default_factory=list)
    scalars: dict[str, Any] = field(default_factory=dict)
    chart_png_b64: str | None = None


class Sandbox(abc.ABC):
    name: str

    @abc.abstractmethod
    async def run(
        self, *, code: str, datasets: list[SandboxDataset], limits: SandboxLimits
    ) -> SandboxResult:
        """Execute `code` against `datasets` under `limits`."""

    @abc.abstractmethod
    async def available(self) -> bool:
        """Whether this sandbox can currently run code with full isolation."""
