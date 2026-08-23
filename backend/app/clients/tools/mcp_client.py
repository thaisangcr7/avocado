"""A Model Context Protocol client, over the Streamable HTTP transport.

Hand-written rather than taken from the MCP SDK, deliberately. A client needs
exactly three calls — `initialize`, `tools/list`, `tools/call` — and the SDK
brings a server framework, a session abstraction and a stdio transport that
this application has no use for. The protocol surface below is smaller than the
dependency would be, and it fails in ways this codebase already handles.

The transport is the current remote one: a single endpoint, JSON-RPC over POST,
where the server may answer with a plain JSON body *or* an SSE stream. Both are
handled, because which one arrives is the server's choice and not ours.

Three properties are load-bearing, and the tests assert each:

- **The token is never logged.** It goes in a header and nowhere else.
- **A hostile server cannot exhaust this process.** Responses are read against
  a byte ceiling, tool listings against a page ceiling, and result text is
  truncated before it can crowd out a model's context window.
- **Server text is data.** It is carried verbatim to be shown, never parsed for
  anything that decides what this code does next.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.clients.tools.base import RemoteTool, ToolCallResult, ToolTransport, ToolTransportError
from app.core.logging import get_logger

log = get_logger(__name__)

# The revision this client speaks. A server that negotiates a different one
# answers with its own, and that is what we echo back on later requests.
PROTOCOL_VERSION = "2025-06-18"

CLIENT_INFO = {"name": "avocado", "version": "0.1.0"}

# A response larger than this is refused rather than read. The body is a tool
# result destined for a context window; nothing legitimate is this big, and
# reading an unbounded one is how a single bad server takes the API down.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

# Tool text is truncated to roughly this before it reaches a model. A server
# that returns a megabyte of text would otherwise evict the conversation the
# tool was called to serve.
MAX_RESULT_CHARS = 24_000

# `tools/list` is paginated. A server that keeps returning a cursor forever
# would loop us indefinitely, so the walk stops and reports what it has.
MAX_LIST_PAGES = 20


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    note = f"\n\n[truncated by Avocado: the tool returned more than {MAX_RESULT_CHARS} characters]"
    return text[:MAX_RESULT_CHARS] + note


class McpClient(ToolTransport):
    """One configured MCP server.

    Holds the negotiated session, so the handshake happens once per instance
    rather than once per call. Instances are cheap; one per server per process
    is the intended shape.
    """

    name = "mcp"

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        timeout: float = 30.0,
        label: str | None = None,
    ) -> None:
        self._url = url
        # Resolved by the caller from the environment. This class receives the
        # value and never the name of it, and never writes it anywhere but a
        # request header.
        self._token = token
        self._timeout = timeout
        # What logs call this server. The URL can carry a credential in a query
        # string on some hosted servers, so it is not what gets logged.
        self._label = label or "mcp-server"
        self._session_id: str | None = None
        self._protocol_version = PROTOCOL_VERSION
        self._initialized = False
        # Two concurrent turns in the same conversation would otherwise both
        # run the handshake and the second would strand the first's session.
        self._handshake = asyncio.Lock()
        self._next_id = 0

    # --- plumbing ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            # Both are permitted answers to a POST; the server picks.
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self._protocol_version,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _rpc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _read_capped(self, response: httpx.Response) -> bytes:
        """Read a response body, refusing one that exceeds the ceiling."""
        body = bytearray()
        async for piece in response.aiter_bytes():
            body.extend(piece)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ToolTransportError(
                    f"'{self._label}' returned more data than Avocado will read."
                )
        return bytes(body)

    @staticmethod
    def _from_sse(body: str) -> dict[str, Any] | None:
        """Pull the last JSON-RPC message out of an SSE stream.

        A server may narrate progress before answering. The answer is the last
        well-formed `data:` payload, and anything unparseable is skipped rather
        than failing the call — a comment or a keep-alive is legal SSE.
        """
        found: dict[str, Any] | None = None
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload:
                continue
            try:
                message = json.loads(payload)
            except ValueError:
                continue
            if isinstance(message, dict) and ("result" in message or "error" in message):
                found = message
        return found

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one JSON-RPC request and return its `result`."""
        payload = {"jsonrpc": "2.0", "id": self._rpc_id(), "method": method}
        if params is not None:
            payload["params"] = params

        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("POST", self._url, json=payload, headers=self._headers()) as response,
            ):
                # Handed out on initialize, and required on every request after
                # it by servers that keep state.
                session = response.headers.get("mcp-session-id")
                if session:
                    self._session_id = session
                content_type = response.headers.get("content-type", "")
                body = await self._read_capped(response)
                status = response.status_code
        except httpx.HTTPError as exc:
            log.warning("mcp_unreachable", server=self._label, error=type(exc).__name__)
            raise ToolTransportError(f"'{self._label}' is unreachable.") from exc

        if status == 404 and self._session_id:
            # The server dropped the session. Clearing it means the next call
            # re-handshakes instead of repeating a request it will never
            # accept again.
            self._session_id = None
            self._initialized = False
        if status >= 400:
            log.warning("mcp_http_error", server=self._label, status=status)
            raise ToolTransportError(f"'{self._label}' refused the request ({status}).")

        text = body.decode("utf-8", errors="replace")
        if "text/event-stream" in content_type:
            message = self._from_sse(text)
            if message is None:
                raise ToolTransportError(f"'{self._label}' sent no usable response.")
        else:
            try:
                parsed = json.loads(text)
            except ValueError as exc:
                raise ToolTransportError(f"'{self._label}' sent a malformed response.") from exc
            if not isinstance(parsed, dict):
                raise ToolTransportError(f"'{self._label}' sent a malformed response.")
            message = parsed

        if "error" in message:
            error = message["error"]
            detail = "unknown error"
            if isinstance(error, dict):
                detail = str(error.get("message") or detail)
            log.warning("mcp_rpc_error", server=self._label, method=method)
            raise ToolTransportError(f"'{self._label}' reported: {detail}")

        result = message.get("result")
        if not isinstance(result, dict):
            raise ToolTransportError(f"'{self._label}' sent a response with no result.")
        return result

    async def _notify(self, method: str) -> None:
        """Fire a notification. It has no id, so there is nothing to wait for."""
        payload = {"jsonrpc": "2.0", "method": method}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                await client.post(self._url, json=payload, headers=self._headers())
        except httpx.HTTPError:
            # A server that ignores the notification is still usable, so this
            # is logged rather than raised.
            log.info("mcp_notify_failed", server=self._label, method=method)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._handshake:
            if self._initialized:
                return
            result = await self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            )
            negotiated = result.get("protocolVersion")
            if isinstance(negotiated, str) and negotiated:
                self._protocol_version = negotiated
            self._initialized = True
            await self._notify("notifications/initialized")
            log.info("mcp_initialized", server=self._label, protocol=self._protocol_version)

    # --- contract ------------------------------------------------------

    async def list_tools(self) -> list[RemoteTool]:
        await self._ensure_initialized()

        tools: list[RemoteTool] = []
        cursor: str | None = None
        for _ in range(MAX_LIST_PAGES):
            params = {"cursor": cursor} if cursor else {}
            result = await self._request("tools/list", params)
            for entry in result.get("tools") or []:
                if not isinstance(entry, dict):
                    continue
                tool_name = entry.get("name")
                if not isinstance(tool_name, str) or not tool_name:
                    continue
                schema = entry.get("inputSchema")
                tools.append(
                    RemoteTool(
                        name=tool_name,
                        description=str(entry.get("description") or ""),
                        input_schema=schema if isinstance(schema, dict) else {},
                    )
                )
            cursor = result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        else:
            log.warning("mcp_list_truncated", server=self._label, pages=MAX_LIST_PAGES)

        log.info("mcp_listed_tools", server=self._label, count=len(tools))
        return tools

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolCallResult:
        await self._ensure_initialized()
        result = await self._request("tools/call", {"name": name, "arguments": arguments})

        parts: list[str] = []
        for block in result.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            else:
                # An image or an embedded resource. Named rather than dropped,
                # so an answer built on it is not silently built on nothing.
                parts.append(f"[{block.get('type') or 'unknown'} content omitted]")

        structured = result.get("structuredContent")
        text = "\n".join(parts).strip()
        if not text and structured is not None:
            text = json.dumps(structured)[:MAX_RESULT_CHARS]

        is_error = bool(result.get("isError"))
        log.info("mcp_tool_called", server=self._label, tool=name, failed=is_error)
        return ToolCallResult(
            text=_truncate(text) or "The tool returned nothing.",
            is_error=is_error,
            structured=structured if isinstance(structured, dict) else None,
        )

    async def available(self) -> bool:
        try:
            await self._ensure_initialized()
            return True
        except ToolTransportError:
            return False
