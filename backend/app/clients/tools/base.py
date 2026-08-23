"""The contract a tool transport satisfies, wherever the tool actually runs.

A caller asks what tools exist and calls one. Whether the answer is served in
this process or by a server on the other side of the internet is the
transport's business — which is what keeps the seventeenth integration a config
row rather than another branch in a service.

**Results from a transport are untrusted input.** A remote server's text is
written by whoever runs that server, and it lands in a model's context. It is
data to be reported, never instruction to be followed, and nothing here treats
it as anything else: no result field selects code paths, and the text is
carried verbatim rather than interpreted.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ProviderError


class ToolTransportError(ProviderError):
    """A tool server could not be reached, or answered in a shape we cannot use.

    Distinct from a tool that ran and *failed*, which is an ordinary
    `ToolCallResult` with `is_error` set. One is the integration being broken;
    the other is the integration working and reporting bad news, and a model
    can be told the second but not the first.
    """

    title = "Tool Server Error"
    error_type = "https://avocado.dev/errors/tool-transport"


@dataclass(frozen=True, slots=True)
class RemoteTool:
    """One callable a transport offers.

    `name` is the server's own name for it, unqualified. Namespacing across
    servers belongs to whatever assembles a catalogue from several transports —
    two servers may legitimately both offer `search`.
    """

    name: str
    description: str
    # JSON Schema for the arguments. Passed to the model as-is, so it is the
    # server's description of its own contract and not a guess at one.
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallResult:
    """What came back from running a tool.

    `text` is what the model is shown. `is_error` means the tool ran and
    reported failure — the model is told, so it can try something else rather
    than treating a failure as an answer.
    """

    text: str
    is_error: bool = False
    structured: dict[str, Any] | None = None


class ToolTransport(abc.ABC):
    """Adapter contract. One implementation per protocol, under `clients/tools/`."""

    name: str

    @abc.abstractmethod
    async def list_tools(self) -> list[RemoteTool]:
        """Everything this transport can run right now.

        Raises `ToolTransportError` rather than returning an empty list when
        the server cannot be reached: "this server offers nothing" and "this
        server is down" have to stay distinguishable, or a broken integration
        silently becomes a tool that does nothing.
        """

    @abc.abstractmethod
    async def call(self, name: str, arguments: dict[str, Any]) -> ToolCallResult:
        """Run one tool and return what it said."""

    async def available(self) -> bool:
        """Cheap reachability probe, for showing a server as connected or not."""
        return True
