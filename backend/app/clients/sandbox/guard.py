"""Static screen of generated code, applied before it reaches the sandbox.

This is defence in depth and explicitly *not* the security boundary — the
container is. Its job is to reject code that has no business in an analysis
task (spawning processes, opening sockets, reading the filesystem outside the
mounted data) early, with a clear message, instead of letting it fail obscurely
inside the sandbox.

Treating this as the boundary would be a mistake: an AST screen is bypassable
in ways a no-network, read-only, capability-dropped container is not.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

BANNED_MODULES = frozenset(
    {
        "socket",
        "subprocess",
        "multiprocessing",
        "ctypes",
        "shutil",
        "urllib",
        "urllib3",
        "http",
        "requests",
        "httpx",
        "ftplib",
        "telnetlib",
        "smtplib",
        "asyncio",
        "importlib",
        "pickle",
        "marshal",
        "pty",
        "signal",
        "resource",
        "webbrowser",
    }
)

# `os` and `sys` are permitted for harmless attribute reads (os.path.join),
# but these specific attributes are not.
BANNED_ATTRIBUTES = frozenset(
    {
        "system",
        "popen",
        "execv",
        "execve",
        "execvp",
        "fork",
        "forkpty",
        "spawnv",
        "spawnve",
        "kill",
        "remove",
        "unlink",
        "rmdir",
        "removedirs",
        "chmod",
        "chown",
        "setuid",
        "setgid",
    }
)

BANNED_NAMES = frozenset({"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"})


# Dunder traversal (`__class__.__bases__`, `__globals__`, `__builtins__`) is
# the classic sandbox-escape primitive, so all of it is refused except a few
# names that legitimately appear in analysis code.
_ALLOWED_DUNDERS = frozenset({"__name__", "__doc__", "__len__", "__dict__"})


def _is_forbidden_dunder(attr: str) -> bool:
    return attr.startswith("__") and attr.endswith("__") and attr not in _ALLOWED_DUNDERS


def _denied(symbol: str) -> str:
    return f"Use of '{symbol}' is not permitted in analysis code."


def _denied_import(module: str) -> str:
    return f"Import of '{module}' is not permitted in analysis code."


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    reason: str | None = None


def screen_code(code: str) -> GuardResult:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return GuardResult(False, f"Generated code is not valid Python: {exc.msg}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BANNED_MODULES:
                    return GuardResult(False, _denied_import(root))

        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BANNED_MODULES:
                return GuardResult(False, _denied_import(root))

        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRIBUTES or _is_forbidden_dunder(node.attr):
                return GuardResult(False, _denied(node.attr))

        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in BANNED_NAMES
        ):
            return GuardResult(False, _denied(node.id))

    return GuardResult(True)
