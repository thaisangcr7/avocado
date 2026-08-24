"""Auto-seed demo data after the API is live.

Intended for deployment bootstrap behind an env flag. It waits for the API
health endpoint, then runs the existing demo generator with an idempotence
check so container restarts do not create duplicate demo organizations.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

DEFAULT_BASE_URL = os.environ.get("DEMO_SEED_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_WAIT_SECONDS = int(os.environ.get("DEMO_SEED_WAIT_SECONDS", "180"))
DEFAULT_POLL_SECONDS = float(os.environ.get("DEMO_SEED_POLL_SECONDS", "1.5"))
DEFAULT_ROWS_PER_CSV = int(os.environ.get("DEMO_SEED_ROWS_PER_CSV", "800"))


def _mark(status: str, detail: str | None = None) -> None:
    """Emit a machine-searchable status line for container logs."""
    if detail:
        print(f"DEMO_SEED_STATUS={status} detail={detail}")
    else:
        print(f"DEMO_SEED_STATUS={status}")


def _enabled() -> bool:
    value = os.environ.get("AUTO_SEED_DEMO", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"DEMO_SEED_BASE_URL must be absolute http(s), got {value!r}.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _wait_for_live(base_url: str, wait_seconds: int, poll_seconds: float) -> bool:
    deadline = time.monotonic() + wait_seconds
    url = f"{base_url}/api/v1/live"

    while time.monotonic() < deadline:
        req = urlrequest.Request(url, method="GET")  # noqa: S310 -- scheme validated in _normalize_base_url
        try:
            with urlrequest.urlopen(req, timeout=5) as response:  # noqa: S310 -- scheme validated in _normalize_base_url
                if 200 <= response.status < 300:
                    return True
        except (urlerror.URLError, TimeoutError):
            pass
        time.sleep(poll_seconds)

    return False


def main() -> int:
    if not _enabled():
        _mark("disabled")
        print("AUTO_SEED_DEMO is disabled; skipping bootstrap seed.")
        return 0

    try:
        base_url = _normalize_base_url(DEFAULT_BASE_URL)
    except ValueError as exc:
        _mark("invalid_config", "bad_base_url")
        print(str(exc), file=sys.stderr)
        return 2

    _mark("waiting_for_api", f"base_url={base_url}")
    ready = _wait_for_live(base_url, DEFAULT_WAIT_SECONDS, DEFAULT_POLL_SECONDS)
    if not ready:
        _mark("api_not_ready", f"timeout_seconds={DEFAULT_WAIT_SECONDS}")
        print(
            f"Demo bootstrap skipped: API did not become live within {DEFAULT_WAIT_SECONDS}s.",
            file=sys.stderr,
        )
        return 1

    command = [
        sys.executable,
        "scripts/generate_demo_data.py",
        "--base-url",
        base_url,
        "--rows-per-csv",
        str(DEFAULT_ROWS_PER_CSV),
        "--skip-if-workspaces-exist",
    ]

    output_dir = os.environ.get("DEMO_SEED_OUTPUT_DIR", "").strip()
    if output_dir:
        command.extend(["--output-dir", output_dir])

    _mark("running")
    print("Starting demo bootstrap seed...")
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    skipped_existing = "Skipping demo seed: database already has" in (completed.stdout or "")
    if completed.returncode == 0 and skipped_existing:
        _mark("skipped_existing_data")
    elif completed.returncode == 0:
        _mark("seeded")

    if completed.returncode != 0:
        _mark("failed", f"exit_code={completed.returncode}")
        print(
            f"Demo bootstrap failed with exit code {completed.returncode}.",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
