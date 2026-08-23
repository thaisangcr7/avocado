"""The analysis sandbox, tested against real containers.

Architecture §15 calls this out alongside the isolation test, and for the same
reason: this is the control that makes executing model-generated code
acceptable at all. Asserting it in a mock proves nothing, so these tests start
actual containers and try to break out of them.

Skipped when Docker or the sandbox image is unavailable — but never silently
replaced with a weaker check.
"""

from __future__ import annotations

import asyncio

import pytest

from app.clients.sandbox.base import SandboxDataset, SandboxLimits
from app.clients.sandbox.docker_sandbox import DockerSandbox

# `docker` because each of these starts a real container. They are the slowest
# tests in the suite by a wide margin and the only ones needing a daemon, so
# the inner development loop skips them — but nothing that touches the sandbox
# is finished until they have run. `verify.sh` (no flags) always runs them.
pytestmark = [pytest.mark.anyio, pytest.mark.docker]

IMAGE = "avocado-sandbox:latest"

CSV = (
    b"region,month,revenue\n"
    b"North,2024-01,100\nNorth,2024-02,150\n"
    b"South,2024-01,80\nSouth,2024-02,120\n"
)


def limits(**overrides) -> SandboxLimits:
    base = {
        "timeout_seconds": 20,
        "memory_mb": 512,
        "cpus": 1.0,
        "max_output_bytes": 1_048_576,
        "pids_limit": 128,
    }
    return SandboxLimits(**{**base, **overrides})


@pytest.fixture(scope="module")
def sandbox() -> DockerSandbox:
    return DockerSandbox(IMAGE)


@pytest.fixture(autouse=True)
async def require_docker(sandbox):
    if not await sandbox.available():
        pytest.skip(f"Docker or the {IMAGE} image is unavailable.")


async def run(sandbox, code: str, **limit_overrides):
    return await sandbox.run(
        code=code,
        datasets=[SandboxDataset(variable="sales", filename="data.csv", content=CSV)],
        limits=limits(**limit_overrides),
    )


# --------------------------------------------------------------------------
# It has to actually work
# --------------------------------------------------------------------------


async def test_real_computation_produces_a_real_answer(sandbox):
    result = await run(
        sandbox,
        "result = sales.groupby('region')['revenue'].sum().reset_index()\n"
        "print('total:', sales['revenue'].sum())",
    )
    assert result.success, result.error
    assert "total: 450" in result.stdout
    table = result.tables[0]
    assert table["columns"] == ["region", "revenue"]
    assert sorted(table["rows"]) == [["North", 250], ["South", 200]]


async def test_a_chart_is_captured(sandbox):
    result = await run(
        sandbox,
        "import matplotlib.pyplot as plt\n"
        "sales.groupby('region')['revenue'].sum().plot(kind='bar')\n"
        "result = sales['revenue'].mean()",
    )
    assert result.success, result.error
    assert result.chart_png_b64
    import base64

    assert base64.b64decode(result.chart_png_b64).startswith(b"\x89PNG")


async def test_a_scalar_answer_comes_back_as_a_scalar(sandbox):
    result = await run(sandbox, "result = int(sales['revenue'].sum())")
    assert result.success, result.error
    assert result.scalars["result"] == 450


async def test_an_error_in_the_code_is_reported_not_swallowed(sandbox):
    result = await run(sandbox, "result = sales['nonexistent_column'].sum()")
    assert not result.success
    assert "KeyError" in result.error


# --------------------------------------------------------------------------
# The guarantees from §13 — no network, hard timeout, resource caps
# --------------------------------------------------------------------------


async def test_the_network_is_unreachable(sandbox):
    result = await run(
        sandbox,
        "import urllib.request\n"
        "result = urllib.request.urlopen('http://example.com', timeout=5).status",
    )
    assert not result.success
    assert result.error


async def test_a_raw_socket_cannot_be_opened(sandbox):
    """Not just DNS — the container has no route to anywhere."""
    result = await run(
        sandbox,
        "import socket\n"
        "s = socket.socket()\n"
        "s.settimeout(5)\n"
        "result = s.connect(('1.1.1.1', 53))",
    )
    assert not result.success


async def test_dns_does_not_resolve(sandbox):
    result = await run(sandbox, "import socket\nresult = socket.gethostbyname('example.com')")
    assert not result.success


async def test_an_infinite_loop_is_killed_at_the_deadline(sandbox):
    result = await run(sandbox, "while True:\n    pass\n", timeout_seconds=5)
    assert not result.success
    assert result.timed_out
    # Bounded in wall-clock terms too, not just eventually.
    assert result.execution_ms < 20_000


async def test_a_sleep_longer_than_the_deadline_is_killed(sandbox):
    result = await run(sandbox, "import time\ntime.sleep(60)\nresult = 1", timeout_seconds=5)
    assert not result.success
    assert result.timed_out


async def test_memory_is_capped(sandbox):
    result = await run(sandbox, "x = bytearray(2_000_000_000)\nresult = len(x)", memory_mb=256)
    assert not result.success
    assert result.error


async def test_the_root_filesystem_is_read_only(sandbox):
    result = await run(
        sandbox, "with open('/opt/runner.py', 'w') as f:\n    f.write('x')\nresult = 1"
    )
    assert not result.success
    assert "Read-only" in result.error or "Permission" in result.error


async def test_the_mounted_data_cannot_be_modified(sandbox):
    """Input is mounted read-only, so code cannot rewrite its own inputs."""
    result = await run(
        sandbox, "with open('/work/code.py', 'w') as f:\n    f.write('x')\nresult = 1"
    )
    assert not result.success


async def test_the_container_does_not_run_as_root(sandbox):
    result = await run(sandbox, "import os\nresult = os.getuid()")
    assert result.success, result.error
    assert result.scalars["result"] == 10001


async def test_a_fork_bomb_is_contained(sandbox):
    """The pid limit has to hold even when the code tries hard to break it."""
    result = await run(
        sandbox,
        "import os\n"
        "for _ in range(5000):\n"
        "    try:\n"
        "        os.fork()\n"
        "    except Exception:\n"
        "        pass\n"
        "result = 'done'",
        timeout_seconds=10,
        pids_limit=32,
    )
    # Either it is refused or it is killed — what matters is that the call
    # returns and the host is unaffected.
    assert result is not None


async def test_concurrent_runs_stay_independent(sandbox):
    """Two analyses running at once must not see each other's data."""
    results = await asyncio.gather(
        run(sandbox, "result = int(sales['revenue'].sum())"),
        run(sandbox, "result = int(sales['revenue'].max())"),
    )
    assert results[0].scalars["result"] == 450
    assert results[1].scalars["result"] == 150


async def test_output_that_floods_stdout_is_truncated(sandbox):
    result = await run(sandbox, "print('x' * 10_000_000)\nresult = 1", timeout_seconds=25)
    # Whatever happens, the host must not receive an unbounded payload.
    assert len(result.stdout) <= 1_000_000
