"""Voice: recorded audio in, retrievable transcript out.

The behaviour that matters is that a transcript is not a second-class thing —
it becomes an ordinary document and is answerable through the same retrieval
path as an uploaded PDF.
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest

from app.clients.stt.base import Transcription
from app.core.errors import ProviderError
from tests.conftest import register_account

pytestmark = pytest.mark.anyio

# A webm container header is enough for type detection; the fake never decodes.
AUDIO = b"\x1a\x45\xdf\xa3" + b"fake audio payload " * 100


async def upload_recording(client, account, filename="standup.webm", data=AUDIO):
    return await client.post(
        f"/workspaces/{account['workspace_id']}/voice",
        files={"file": (filename, io.BytesIO(data), "audio/webm")},
        headers=account["headers"],
    )


async def wait_for_transcript(client, account, recording_id, attempts=80):
    for _ in range(attempts):
        response = await client.get(
            f"/workspaces/{account['workspace_id']}/voice/{recording_id}",
            headers=account["headers"],
        )
        if response.status_code == 200 and response.json()["transcript_status"] in (
            "ready",
            "failed",
        ):
            return response.json()
        await asyncio.sleep(0.05)
    raise AssertionError("Transcription never finished.")


# --- capabilities ----------------------------------------------------------


async def test_capabilities_report_voice_is_available(client, account):
    response = await client.get("/voice/capabilities", headers=account["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["live_transcription"] is True
    assert body["max_audio_mb"] > 0


async def test_capabilities_report_disabled_when_unconfigured(client, account, app):
    """The client asks first so it can hide the mic rather than offer a button
    that fails when pressed."""
    app.state.transcriber = None
    response = await client.get("/voice/capabilities", headers=account["headers"])
    assert response.json() == {
        "enabled": False,
        "provider": None,
        "live_transcription": False,
        "max_audio_mb": 0,
        "max_stream_seconds": 0,
    }


async def test_capabilities_require_authentication(client):
    assert (await client.get("/voice/capabilities")).status_code == 401


# --- upload and transcription ---------------------------------------------


async def test_a_recording_becomes_a_retrievable_document(client, account, fake_stt):
    response = await upload_recording(client, account)
    assert response.status_code == 201
    recording_id = response.json()["recording"]["id"]
    assert response.json()["recording"]["transcript_status"] == "pending"

    recording = await wait_for_transcript(client, account, recording_id)
    assert recording["transcript_status"] == "ready", recording.get("error_message")
    assert "analysis engine" in recording["transcript"]
    assert recording["duration_seconds"] == 12.5
    assert fake_stt.calls == 1

    # The transcript is now a document, ingested like any other source.
    assert recording["document_id"]

    # Waited for separately: the recording is marked ready inside
    # transcription, and its transcript is only ingested afterwards. The two
    # have their own lifecycles, so a ready recording does not imply a ready
    # document.
    from tests.integration.test_documents import wait_for_ready

    body = await wait_for_ready(client, recording["document_id"], account["headers"])
    assert body["status"] == "ready", body.get("error_message")
    assert body["doc_type"] == "audio"
    assert body["chunk_count"] > 0
    assert body["doc_metadata"]["source"] == "voice"
    assert body["doc_metadata"]["recording_id"] == recording_id


async def test_the_transcript_is_answerable_through_normal_retrieval(client, account, fake_stt):
    """The point of the whole pipeline: a meeting becomes searchable knowledge."""
    fake_stt.transcription = Transcription(
        text=(
            "Speaker 0: The zylophone migration is scheduled for March. "
            "Speaker 1: We need two engineers on it."
        )
        * 5,
        duration_seconds=45.0,
        model="fake-nova",
    )
    response = await upload_recording(client, account, "planning.webm")
    recording = await wait_for_transcript(client, account, response.json()["recording"]["id"])
    # Retrieval needs the transcript's *chunks*, which are written by ingestion
    # after the recording is marked ready — two separate lifecycles.
    from tests.integration.test_documents import wait_for_ready

    await wait_for_ready(client, recording["document_id"], account["headers"])

    conversation = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations",
        json={},
        headers=account["headers"],
    )
    reply = await client.post(
        f"/workspaces/{account['workspace_id']}/conversations/{conversation.json()['id']}/messages",
        json={"content": "zylophone migration scheduled March engineers"},
        headers=account["headers"],
    )

    assert reply.status_code == 201
    citations = reply.json()["assistant_message"]["citations"]
    assert citations, "the recording's transcript should be retrievable"
    assert "transcript" in citations[0]["document_name"]


async def test_audio_metadata_survives_onto_the_document(client, account):
    response = await upload_recording(client, account)
    recording = await wait_for_transcript(client, account, response.json()["recording"]["id"])
    document = await client.get(
        f"/documents/{recording['document_id']}", headers=account["headers"]
    )
    metadata = document.json()["doc_metadata"]

    # The original audio stays referenced so the recording can be
    # re-transcribed later without asking for another upload.
    assert metadata["audio_key"]
    assert metadata["stt_model"] == "fake-nova"
    assert metadata["duration_seconds"] == 12.5
    assert metadata["speaker_count"] == 1


async def test_an_unsupported_audio_format_is_rejected(client, account):
    response = await client.post(
        f"/workspaces/{account['workspace_id']}/voice",
        files={"file": ("notes.txt", io.BytesIO(b"not audio"), "text/plain")},
        headers=account["headers"],
    )
    assert response.status_code == 415


async def test_an_empty_recording_is_rejected(client, account):
    response = await upload_recording(client, account, data=b"")
    assert response.status_code == 422


async def test_an_oversized_recording_is_rejected(client, account, app):
    limit = app.state.settings.max_audio_bytes
    response = await upload_recording(client, account, data=b"x" * (limit + 1024))
    assert response.status_code == 413


async def test_silence_is_reported_rather_than_stored_as_an_empty_document(
    client, account, fake_stt
):
    fake_stt.transcription = Transcription(text="   ", duration_seconds=3.0)
    response = await upload_recording(client, account)
    recording = await wait_for_transcript(client, account, response.json()["recording"]["id"])

    assert recording["transcript_status"] == "failed"
    assert "No speech" in recording["error_message"]
    assert recording["document_id"] is None


async def test_a_provider_failure_is_recorded_not_lost(client, account, fake_stt):
    """Transcription runs in the background, so a failure has to be visible in
    the recording's own status rather than only in a worker traceback."""
    fake_stt.error = ProviderError("Transcription failed (503).")

    response = await upload_recording(client, account)
    recording = await wait_for_transcript(client, account, response.json()["recording"]["id"])
    assert recording["transcript_status"] == "failed"
    assert "503" in recording["error_message"]


async def test_upload_is_refused_when_transcription_is_not_configured(client, account, app):
    app.state.transcriber = None
    response = await upload_recording(client, account)
    assert response.status_code == 502
    assert "not configured" in response.json()["detail"]


# --- listing, fetching, deletion ------------------------------------------


async def test_recordings_are_listed_for_the_workspace(client, account):
    await upload_recording(client, account, "one.webm")
    await upload_recording(client, account, "two.webm")

    response = await client.get(
        f"/workspaces/{account['workspace_id']}/voice", headers=account["headers"]
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_a_missing_recording_reads_as_not_found(client, account):
    response = await client.get(
        f"/workspaces/{account['workspace_id']}/voice/{uuid.uuid4()}",
        headers=account["headers"],
    )
    assert response.status_code == 404


async def test_deleting_a_recording_keeps_its_transcript_document(client, account):
    """Deleting the audio should not silently remove knowledge the team has
    been building on — the document is deletable on its own terms."""
    response = await upload_recording(client, account)
    recording_id = response.json()["recording"]["id"]
    recording = await wait_for_transcript(client, account, recording_id)
    document_id = recording["document_id"]

    deleted = await client.delete(
        f"/workspaces/{account['workspace_id']}/voice/{recording_id}",
        headers=account["headers"],
    )
    assert deleted.status_code == 200

    assert (
        await client.get(
            f"/workspaces/{account['workspace_id']}/voice/{recording_id}",
            headers=account["headers"],
        )
    ).status_code == 404
    assert (
        await client.get(f"/documents/{document_id}", headers=account["headers"])
    ).status_code == 200


# --- tenant isolation ------------------------------------------------------


async def test_recordings_do_not_cross_the_tenant_boundary(client):
    alice = await register_account(client, email="alice@alpha.com", org="Alpha")
    bob = await register_account(client, email="bob@beta.com", org="Beta")

    uploaded = await upload_recording(client, bob, "beta-standup.webm")
    recording_id = uploaded.json()["recording"]["id"]

    # Alice cannot read Bob's recording through his workspace...
    assert (
        await client.get(
            f"/workspaces/{bob['workspace_id']}/voice/{recording_id}",
            headers=alice["headers"],
        )
    ).status_code == 404
    # ...nor by naming it under her own.
    assert (
        await client.get(
            f"/workspaces/{alice['workspace_id']}/voice/{recording_id}",
            headers=alice["headers"],
        )
    ).status_code == 404
    # ...nor upload into his workspace.
    assert (
        await client.post(
            f"/workspaces/{bob['workspace_id']}/voice",
            files={"file": ("x.webm", io.BytesIO(AUDIO), "audio/webm")},
            headers=alice["headers"],
        )
    ).status_code == 404


async def test_a_transcript_joins_the_knowledge_map(client, account, fake_llm):
    """A transcript is a document like any other. Without classification a
    meeting recording is retrievable but invisible to 'what does this team
    do?', which is the whole point of the knowledge layer."""
    import json

    from tests.integration.test_documents import wait_for_ready

    fake_llm.responses = [
        json.dumps(
            {
                "kind": "process",
                "title": "Standup notes",
                "summary": "A recorded discussion of what the team agreed.",
                "topics": ["standup"],
                "effective_date": None,
                "confidence": 0.8,
            }
        )
    ]

    response = await upload_recording(client, account, "standup.webm")
    recording = await wait_for_transcript(client, account, response.json()["recording"]["id"])
    await wait_for_ready(client, recording["document_id"], account["headers"])

    classification = await client.get(
        f"/workspaces/{account['workspace_id']}/documents/{recording['document_id']}/classification",
        headers=account["headers"],
    )
    assert classification.status_code == 200, classification.text
    assert classification.json()["kind"] == "process"

    knowledge = await client.get(
        f"/workspaces/{account['workspace_id']}/knowledge", headers=account["headers"]
    )
    assert knowledge.json()["unclassified_count"] == 0
