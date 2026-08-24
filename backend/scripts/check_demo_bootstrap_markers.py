"""One-shot guard for demo bootstrap observability markers.

This check is intentionally narrow and fast: it does not start the API or touch
Docker. It verifies that AUTO_SEED_DEMO paths still emit the status markers
operators rely on in logs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
AUTO_SEED_SCRIPT = SCRIPT_DIR / "auto_seed_demo.py"


@dataclass(frozen=True)
class Case:
    name: str
    env: dict[str, str]
    expected_exit: int
    expected_markers: tuple[str, ...]


def run_case(case: Case) -> tuple[bool, str]:
    env = os.environ.copy()
    env.update(case.env)

    completed = subprocess.run(
        [sys.executable, str(AUTO_SEED_SCRIPT)],
        cwd=str(SCRIPT_DIR.parent),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = f"{completed.stdout}\n{completed.stderr}"

    if completed.returncode != case.expected_exit:
        return False, (
            f"[{case.name}] expected exit {case.expected_exit} but got "
            f"{completed.returncode}.\n{output}"
        )

    for marker in case.expected_markers:
        if marker not in output:
            return False, f"[{case.name}] missing marker: {marker}\n{output}"

    return True, f"[{case.name}] ok"


def main() -> int:
    cases = [
        Case(
            name="disabled",
            env={"AUTO_SEED_DEMO": "false"},
            expected_exit=0,
            expected_markers=("DEMO_SEED_STATUS=disabled",),
        ),
        Case(
            name="timeout",
            env={
                "AUTO_SEED_DEMO": "true",
                "DEMO_SEED_BASE_URL": "http://127.0.0.1:65535",
                "DEMO_SEED_WAIT_SECONDS": "1",
                "DEMO_SEED_POLL_SECONDS": "0.05",
            },
            expected_exit=1,
            expected_markers=(
                "DEMO_SEED_STATUS=waiting_for_api",
                "DEMO_SEED_STATUS=api_not_ready",
            ),
        ),
    ]

    failures: list[str] = []
    for case in cases:
        ok, detail = run_case(case)
        print(detail)
        if not ok:
            failures.append(detail)

    if failures:
        print("demo bootstrap marker check failed", file=sys.stderr)
        return 1

    print("demo bootstrap marker check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
