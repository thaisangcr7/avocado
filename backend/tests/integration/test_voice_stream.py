"""The live dictation socket.

Auth over a WebSocket is the part worth guarding: the token travels in the
first message rather than the URL, because URLs land in access logs, proxy
history and browser history, and a bearer token in any of those is a leak.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from tests.conftest import register_account

pytestmark = pytest.mark.anyio

WS_PATH = "/api/v1/voice/stream"


@contextmanager
def ws_session(app, *, fake_stt):
    """A sync TestClient for the dictation socket.

    Entering TestClient runs the real lifespan, and that is deliberate here:
    the app must build its own database engine inside TestClient's event loop.
    An engine created on the test's loop cannot be used from the portal's —
    asyncpg connections are loop-bound and raise "attached to a different
    loop".

    So lifespan supplies the real infrastructure (pointed at the test database
    by DATABASE_URL) and only the transcriber is swapped, which is the one
    outbound dependency this path actually uses.
    """
    with TestClient(app) as client:
        app.state.transcriber = fake_stt
        yield client


@pytest.fixture
def doubles(fake_stt):  # type: ignore[no-untyped-def]
    return {"fake_stt": fake_stt}


async def test_a_full_dictation_round_trip(client, account, app, fake_stt, doubles):
    creds = {
        "type": "auth",
        "token": account["headers"]["Authorization"].removeprefix("Bearer "),
        "workspace_id": account["workspace_id"],
    }

    with (
        ws_session(app, **doubles) as sync_client,
        sync_client.websocket_connect(WS_PATH) as ws,
    ):
        ws.send_json(creds)
        assert ws.receive_json() == {"type": "ready"}

        ws.send_bytes(b"audio-frame-1")
        ws.send_bytes(b"audio-frame-2")
        ws.send_json({"type": "stop"})

        received = []
        while True:
            message = ws.receive_json()
            if message["type"] in ("done", "error"):
                received.append(message)
                break
            received.append(message)

    transcripts = [m for m in received if m["type"] == "transcript"]
    # Interim segments arrive first and are superseded; only the last is final.
    assert [t["is_final"] for t in transcripts] == [False, False, True]
    assert transcripts[-1]["text"] == "What is the remote work policy?"
    assert received[-1]["type"] == "done"

    # The audio the client sent actually reached the provider.
    assert b"audio-frame-1" in fake_stt.received_audio


async def test_a_socket_without_an_auth_frame_is_closed(app, doubles):
    with (
        ws_session(app, **doubles) as sync_client,
        sync_client.websocket_connect(WS_PATH) as ws,
    ):
        ws.send_json({"type": "audio"})  # not an auth frame
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == 1008


async def test_an_invalid_token_is_rejected(app, account, doubles):
    with (
        ws_session(app, **doubles) as sync_client,
        sync_client.websocket_connect(WS_PATH) as ws,
    ):
        ws.send_json(
            {
                "type": "auth",
                "token": "not-a-real-token",
                "workspace_id": account["workspace_id"],
            }
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == 1008


async def test_a_refresh_token_cannot_open_the_socket(app, account, doubles):
    """Only an access token authenticates; token kinds are not interchangeable."""
    with (
        ws_session(app, **doubles) as sync_client,
        sync_client.websocket_connect(WS_PATH) as ws,
    ):
        ws.send_json(
            {
                "type": "auth",
                "token": account["tokens"]["refresh_token"],
                "workspace_id": account["workspace_id"],
            }
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == 1008


async def test_a_workspace_the_user_cannot_reach_is_refused(client, app, account, doubles):
    """Tenant isolation holds on the socket exactly as it does over HTTP."""
    other = await register_account(client, email="stranger@other.com", org="Other")

    with (
        ws_session(app, **doubles) as sync_client,
        sync_client.websocket_connect(WS_PATH) as ws,
    ):
        ws.send_json(
            {
                "type": "auth",
                "token": account["headers"]["Authorization"].removeprefix("Bearer "),
                "workspace_id": other["workspace_id"],
            }
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == 1008


async def test_an_unknown_workspace_is_refused(app, account, doubles):
    with (
        ws_session(app, **doubles) as sync_client,
        sync_client.websocket_connect(WS_PATH) as ws,
    ):
        ws.send_json(
            {
                "type": "auth",
                "token": account["headers"]["Authorization"].removeprefix("Bearer "),
                "workspace_id": str(uuid.uuid4()),
            }
        )
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
    assert caught.value.code == 1008


async def test_an_authenticated_socket_says_so_when_voice_is_unconfigured(app, account, doubles):
    with ws_session(app, **doubles) as sync_client:
        # Disabled after the doubles are applied, so this reflects a real
        # deployment with no DEEPGRAM_API_KEY rather than a broken fixture.
        app.state.transcriber = None
        with sync_client.websocket_connect(WS_PATH) as ws:
            ws.send_json(
                {
                    "type": "auth",
                    "token": account["headers"]["Authorization"].removeprefix("Bearer "),
                    "workspace_id": account["workspace_id"],
                }
            )
            message = ws.receive_json()

    assert message["type"] == "error"
    assert "not configured" in message["detail"]
