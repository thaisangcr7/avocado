"""The static screen applied to generated code before execution.

This is defence in depth, not the security boundary — the container is. These
tests confirm the screen catches the obvious cases early and does not reject
ordinary analysis code.
"""

from __future__ import annotations

import pytest

from app.clients.sandbox.guard import screen_code


@pytest.mark.parametrize(
    "code",
    [
        "result = sales.groupby('region')['revenue'].sum()",
        "import pandas as pd\nresult = pd.DataFrame({'a': [1]})",
        "result = df[df['x'] > 5].describe()",
        "import matplotlib.pyplot as plt\ndf.plot()\nresult = df.mean()",
        "import numpy as np\nresult = np.mean(df['v'])",
        "result = df.apply(lambda r: r['a'] + r['b'], axis=1)",
    ],
)
def test_ordinary_analysis_code_is_allowed(code):
    assert screen_code(code).allowed, screen_code(code).reason


@pytest.mark.parametrize(
    "code",
    [
        "import socket",
        "import subprocess",
        "from urllib import request",
        "import requests",
        "import os\nos.system('ls')",
        "eval('1+1')",
        "exec('x=1')",
        "__import__('os')",
        "open('/etc/passwd').read()",
        "result = ().__class__.__bases__[0].__subclasses__()",
        "import ctypes",
        "import pickle",
        "os.remove('/tmp/x')",
    ],
)
def test_escape_attempts_are_rejected(code):
    result = screen_code(code)
    assert not result.allowed
    assert result.reason


def test_syntax_error_is_reported_as_such():
    result = screen_code("result = (((")
    assert not result.allowed
    assert "not valid Python" in result.reason


def test_harmless_dunders_are_still_allowed():
    assert screen_code("result = len(df.__dict__)").allowed
