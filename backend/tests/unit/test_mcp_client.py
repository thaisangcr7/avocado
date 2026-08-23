"""The MCP client, against a fake server.

No network and no MCP server process: `httpx.MockTransport` answers the
requests, which means these tests assert the protocol this client actually
speaks rather than whether one particular vendor was reachable that morning.

The properties worth protecting are the ones a broken integration would
otherwise expose quietly: the handshake happening once, the session being
carried, the token staying out of the logs, and a hostile server being unable
to exhaust either this process or a model's context window.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.clients.tools.base import ToolTransportError
from app.clients.tools.mcp_client import (
    MAX_LIST_PAGES,
    MAX_RESPONSE_BYTES,
    MAX_RESULT_CHARS,
    PROTOCOL_VERSION,
    McpClient,
)

pytestmark = pytest.mark.anyio

URL = "https://tools.example.com/mcp"

# Captured at import: re-reading it inside the helper would wrap an
# already-patched client on a second call, and the first transport would win.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def rpc_result(request: httpx.Request, result: dict, **headers: str) -> httpx.Response:
    """A well-formed JSON-RPC success carrying the request's own id."""
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": body.get("id"), "result": result},
        headers=headers,
    )


def make_client(monkeypatch, handler, **kwargs) -> McpClient:
    def patched(*args, **client_kwargs):
        client_kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **client_kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    return McpClient(url=URL, label="fake", **kwargs)


def server(tools=None, call_result=None, *, session: str | None = None, record=None):
    """A minimal MCP server: handshake, one listing, one call."""
    tools = tools if tools is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if record is not None:
            record.append((method, dict(request.headers), body))

        if method == "initialize":
            headers = {"mcp-session-id": session} if session else {}
            return rpc_result(
                request,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "1"},
                },
                **headers,
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return rpc_result(request, {"tools": tools})
        if method == "tools/call":
            return rpc_result(request, call_result or {"content": [{"type": "text", "text": "ok"}]})
        return httpx.Response(404)

    return handler


WEATHER = {
    "name": "get_weather",
    "description": "Current conditions for a city.",
    "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}},
}


async def test_it_lists_what_the_server_offers(monkeypatch):
    client = make_client(monkeypatch, server(tools=[WEATHER]))

    tools = await client.list_tools()

    assert [t.name for t in tools] == ["get_weather"]
    assert tools[0].description == "Current conditions for a city."
    # The schema is handed to the model as the server wrote it, not a guess.
    assert tools[0].input_schema["properties"]["city"] == {"type": "string"}


async def test_it_handshakes_once_across_calls(monkeypatch):
    record: list = []
    client = make_client(monkeypatch, server(tools=[WEATHER], record=record))

    await client.list_tools()
    await client.call("get_weather", {"city": "Hanoi"})

    methods = [method for method, _, _ in record]
    assert methods.count("initialize") == 1, "the handshake must not repeat per call"
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/call"]


async def test_it_carries_the_session_the_server_assigned(monkeypatch):
    record: list = []
    client = make_client(monkeypatch, server(tools=[WEATHER], session="sess-42", record=record))

    await client.list_tools()

    after_handshake = [headers for method, headers, _ in record if method == "tools/list"]
    assert after_handshake[0]["mcp-session-id"] == "sess-42"


async def test_it_sends_the_credential_as_a_header_only(monkeypatch):
    record: list = []
    client = make_client(monkeypatch, server(record=record), token="secret-token")

    await client.list_tools()

    for _, headers, body in record:
        assert headers["authorization"] == "Bearer secret-token"
        # A credential in a body or a query string ends up in server logs and
        # in any proxy between here and there.
        assert "secret-token" not in json.dumps(body)


async def test_the_token_never_reaches_the_logs(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = make_client(monkeypatch, handler, token="secret-token")

    with pytest.raises(ToolTransportError):
        await client.list_tools()

    assert "secret-token" not in caplog.text
    # Nor does the URL, which can itself carry a credential on hosted servers.
    assert URL not in caplog.text


async def test_it_reads_a_server_that_answers_over_sse(monkeypatch):
    """The server picks the response shape, so both have to work."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if method == "notifications/initialized":
            return httpx.Response(202)
        result = (
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}}
            if method == "initialize"
            else {"content": [{"type": "text", "text": "22C and clear"}]}
        )
        message = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        stream = f": keep-alive\n\nevent: message\ndata: {message}\n\n"
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    client = make_client(monkeypatch, handler)

    result = await client.call("get_weather", {"city": "Hanoi"})

    assert result.text == "22C and clear"
    assert result.is_error is False


async def test_a_tool_failure_is_reported_not_raised(monkeypatch):
    """A tool that ran and failed is news for the model, not a broken integration."""
    failed = {"content": [{"type": "text", "text": "No such city."}], "isError": True}
    client = make_client(monkeypatch, server(call_result=failed))

    result = await client.call("get_weather", {"city": "Atlantis"})

    assert result.is_error is True
    assert result.text == "No such city."


async def test_a_protocol_error_is_raised(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return rpc_result(request, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32601, "message": "Unknown tool"},
            },
        )

    client = make_client(monkeypatch, handler)

    with pytest.raises(ToolTransportError, match="Unknown tool"):
        await client.call("nope", {})


async def test_an_unreachable_server_is_an_error_not_an_empty_listing(monkeypatch):
    """ "Offers nothing" and "is down" must stay distinguishable."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = make_client(monkeypatch, handler)

    with pytest.raises(ToolTransportError, match="unreachable"):
        await client.list_tools()
    assert await client.available() is False


async def test_oversized_text_is_truncated_before_it_reaches_a_model(monkeypatch):
    flood = "x" * (MAX_RESULT_CHARS * 2)
    client = make_client(
        monkeypatch, server(call_result={"content": [{"type": "text", "text": flood}]})
    )

    result = await client.call("firehose", {})

    assert len(result.text) < MAX_RESULT_CHARS + 200
    assert "truncated by Avocado" in result.text


async def test_an_oversized_body_is_refused_rather_than_read(monkeypatch):
    """A server cannot make this process hold an unbounded response."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return rpc_result(request, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, content=b"{" + b"a" * (MAX_RESPONSE_BYTES + 1024))

    client = make_client(monkeypatch, handler)

    with pytest.raises(ToolTransportError, match="more data than"):
        await client.list_tools()


async def test_it_walks_pagination_but_not_forever(monkeypatch):
    """A server that always returns a cursor must not loop us indefinitely."""
    pages = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if method == "initialize":
            return rpc_result(request, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        pages["count"] += 1
        return rpc_result(
            request,
            {"tools": [{"name": f"tool_{pages['count']}"}], "nextCursor": "more"},
        )

    client = make_client(monkeypatch, handler)

    tools = await client.list_tools()

    # It stops at the ceiling rather than at the server's say-so, and keeps
    # what it collected instead of failing the whole listing.
    assert pages["count"] == MAX_LIST_PAGES
    assert len(tools) == MAX_LIST_PAGES
