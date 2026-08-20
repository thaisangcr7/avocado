"""Docker-backed analysis sandbox.

Every isolation guarantee is a `docker run` flag, applied unconditionally on
every invocation — there is no code path that omits one:

  --network=none            no network, full stop
  --read-only               immutable root filesystem
  --tmpfs /tmp              the only writable location, size-capped, nosuid/noexec
  --memory / --memory-swap  equal values, so a limit cannot be escaped via swap
  --cpus                    CPU quota
  --pids-limit              blocks fork bombs
  --cap-drop=ALL            no Linux capabilities
  --security-opt=no-new-privileges  setuid binaries cannot elevate
  --user 10001:10001        never root

Data goes in through a read-only bind mount. Results come back on stdout as a
single JSON object; nothing the executed code produces can reach the host
filesystem. The timeout is enforced from the host with a hard kill, so code
that ignores or blocks signals is still bounded.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from app.clients.sandbox.base import Sandbox, SandboxDataset, SandboxLimits, SandboxResult
from app.core.logging import get_logger

log = get_logger(__name__)

# Grace period for container startup on top of the in-container budget. The
# runner enforces the deadline itself and reports a clean timeout; this host
# kill is the backstop for code that wedges the interpreter so the in-container
# alarm never fires. Measured cold start is ~1.5s, so 10s is ample.
_DOCKER_OVERHEAD_SECONDS = 10


class DockerSandbox(Sandbox):
    name = "docker"

    def __init__(self, image: str, *, work_root: str | None = None) -> None:
        self._image = image
        # Where the per-run directory is created.
        #
        # This matters whenever the caller is itself a container talking to the
        # host daemon: a bind mount source is resolved by the *host*, so a path
        # that exists only inside this container mounts as an empty directory
        # and the analysis exits immediately with nothing to read. Pointing
        # both at the same shared path makes the two agree.
        self._work_root = work_root or None

    async def available(self) -> bool:
        """True only if the daemon responds *and* the sandbox image exists."""
        docker = shutil.which("docker")
        if not docker:
            return False
        try:
            process = await asyncio.create_subprocess_exec(
                docker,
                "image",
                "inspect",
                self._image,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return await asyncio.wait_for(process.wait(), timeout=10) == 0
        except (TimeoutError, OSError):
            return False

    def _docker_args(self, work_dir: Path, limits: SandboxLimits, name: str) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            # --- isolation, applied unconditionally ---
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user",
            "10001:10001",
            f"--memory={limits.memory_mb}m",
            # Equal to --memory: without this, the container can swap past its
            # memory cap instead of being killed at it.
            f"--memory-swap={limits.memory_mb}m",
            f"--cpus={limits.cpus}",
            f"--pids-limit={limits.pids_limit}",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",  # noqa: S108 - path inside the container
            # --- data in, read-only ---
            "--mount",
            f"type=bind,source={work_dir},target=/work,readonly",
            "--workdir",
            "/tmp",  # noqa: S108 - path inside the container
            self._image,
        ]

    async def run(
        self, *, code: str, datasets: list[SandboxDataset], limits: SandboxLimits
    ) -> SandboxResult:
        started = time.perf_counter()
        container_name = f"avocado-analysis-{uuid.uuid4().hex[:12]}"

        with tempfile.TemporaryDirectory(prefix="avocado-sandbox-", dir=self._work_root) as tmp:
            work_dir = Path(tmp)
            data_dir = work_dir / "data"
            data_dir.mkdir()

            (work_dir / "code.py").write_text(code)
            for dataset in datasets:
                (data_dir / dataset.filename).write_bytes(dataset.content)
            (work_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "timeout_seconds": limits.timeout_seconds,
                        "datasets": [
                            {"variable": d.variable, "filename": d.filename} for d in datasets
                        ],
                    }
                )
            )
            # The container runs unprivileged; the mount must be traversable
            # by that uid.
            work_dir.chmod(0o755)
            data_dir.chmod(0o755)
            for path in work_dir.rglob("*"):
                path.chmod(0o644 if path.is_file() else 0o755)

            args = self._docker_args(work_dir, limits, container_name)

            try:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                log.error("sandbox_spawn_failed", error=str(exc))
                return SandboxResult(
                    success=False,
                    error="Could not start the analysis sandbox.",
                    execution_ms=int((time.perf_counter() - started) * 1000),
                )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=limits.timeout_seconds + _DOCKER_OVERHEAD_SECONDS,
                )
            except TimeoutError:
                await self._force_kill(container_name, process)
                return SandboxResult(
                    success=False,
                    timed_out=True,
                    error=f"Analysis exceeded the {limits.timeout_seconds}s time limit.",
                    execution_ms=int((time.perf_counter() - started) * 1000),
                )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        stdout_text = stdout[: limits.max_output_bytes].decode("utf-8", errors="replace")
        stderr_text = stderr[:8192].decode("utf-8", errors="replace")

        if process.returncode != 0 and not stdout_text.strip():
            # Non-zero with no JSON on stdout means the container died before
            # the harness could report — OOM kill is by far the usual cause.
            oom = process.returncode == 137
            return SandboxResult(
                success=False,
                stderr=stderr_text,
                error=(
                    f"Analysis exceeded the {limits.memory_mb}MB memory limit."
                    if oom
                    else "The analysis sandbox exited unexpectedly."
                ),
                execution_ms=elapsed_ms,
            )

        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError:
            log.warning("sandbox_bad_payload", returncode=process.returncode)
            return SandboxResult(
                success=False,
                stdout=stdout_text[:4000],
                stderr=stderr_text,
                error="The analysis sandbox returned an unreadable result.",
                execution_ms=elapsed_ms,
            )

        return SandboxResult(
            success=bool(payload.get("success")),
            stdout=payload.get("stdout", ""),
            stderr=stderr_text,
            error=payload.get("error"),
            timed_out=bool(payload.get("timed_out")),
            tables=payload.get("tables", []),
            scalars=payload.get("scalars", {}),
            chart_png_b64=payload.get("chart_png_b64"),
            execution_ms=elapsed_ms,
        )

    async def _force_kill(self, container_name: str, process) -> None:
        """Kill the container, then the client process.

        Terminating the `docker run` client alone can leave the container
        running, so the container is killed by name first.
        """
        try:
            killer = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=10)
        except (TimeoutError, OSError) as exc:
            log.error("sandbox_kill_failed", container=container_name, error=str(exc))

        if process.returncode is None:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                log.error("sandbox_client_kill_timeout", container=container_name)
