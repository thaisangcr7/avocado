"""In-sandbox execution harness.

Runs inside the isolated container, never on the host. Loads each mounted CSV
into a pandas DataFrame, executes the generated snippet, and prints exactly one
JSON object on stdout — the only channel out of the container. Nothing is
written to a shared volume, so there is no path for the executed code to leave
bytes behind on the host.
"""

from __future__ import annotations

import base64
import io
import json
import os
import signal
import sys
import traceback
from contextlib import redirect_stdout

import matplotlib

matplotlib.use("Agg")  # No display inside the container.
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

WORK_DIR = "/work"
MAX_TABLE_ROWS = 200
MAX_TABLE_COLS = 50
MAX_STDOUT_CHARS = 200_000


class _Timeout(Exception):
    """Raised in-container when the analysis outruns its deadline."""


def _on_timeout(_signum, _frame):
    raise _Timeout


def _json_safe(value):
    """Coerce numpy/pandas scalars into something json.dumps accepts."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, float):
        return None if (value != value or value in (float("inf"), float("-inf"))) else value
    return value


def _frame_to_table(name, frame):
    truncated = len(frame) > MAX_TABLE_ROWS or len(frame.columns) > MAX_TABLE_COLS
    view = frame.iloc[:MAX_TABLE_ROWS, :MAX_TABLE_COLS]
    return {
        "name": name,
        "columns": [str(c) for c in view.columns],
        "rows": [[_json_safe(v) for v in row] for row in view.itertuples(index=False)],
        "total_rows": int(len(frame)),
        "truncated": truncated,
    }


def _capture_chart():
    """Return the current matplotlib figure as base64 PNG, if one was drawn."""
    if not plt.get_fignums():
        return None
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close("all")
    return base64.b64encode(buffer.getvalue()).decode()


def main() -> int:
    manifest_path = os.path.join(WORK_DIR, "manifest.json")
    with open(manifest_path) as fh:
        manifest = json.load(fh)

    # Self-imposed deadline. The host also kills the container, but expiring
    # in here first means the user gets a clean "timed out" result instead of
    # an opaque killed-container error.
    deadline = int(manifest.get("timeout_seconds", 30))
    signal.signal(signal.SIGALRM, _on_timeout)
    signal.alarm(deadline)

    namespace = {"pd": pd, "np": np, "plt": plt}
    for entry in manifest["datasets"]:
        path = os.path.join(WORK_DIR, "data", entry["filename"])
        namespace[entry["variable"]] = pd.read_csv(path)

    with open(os.path.join(WORK_DIR, "code.py")) as fh:
        code = fh.read()

    stdout_buffer = io.StringIO()
    result = {
        "success": False,
        "stdout": "",
        "error": None,
        "timed_out": False,
        "tables": [],
        "scalars": {},
        "chart_png_b64": None,
    }

    try:
        with redirect_stdout(stdout_buffer):
            exec(compile(code, "<analysis>", "exec"), namespace)  # noqa: S102
        result["success"] = True
        signal.alarm(0)
    except _Timeout:
        result["error"] = f"Analysis exceeded the {deadline}s time limit."
        result["timed_out"] = True
    except Exception:
        # Only the traceback frames belonging to the generated code are useful
        # to the model on a retry; harness frames are noise.
        result["error"] = traceback.format_exc(limit=3)

    result["stdout"] = stdout_buffer.getvalue()[:MAX_STDOUT_CHARS]

    # `result` is the conventional output variable the prompt asks the model to
    # assign. Anything else the code left behind is ignored.
    produced = namespace.get("result")
    if isinstance(produced, pd.DataFrame):
        result["tables"].append(_frame_to_table("result", produced))
    elif isinstance(produced, pd.Series):
        result["tables"].append(_frame_to_table("result", produced.to_frame(name="value")))
    elif produced is not None:
        result["scalars"]["result"] = _json_safe(produced)

    try:
        result["chart_png_b64"] = _capture_chart()
    except Exception:  # A chart failure must not fail the whole analysis.
        result["chart_png_b64"] = None

    sys.stdout.write(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
