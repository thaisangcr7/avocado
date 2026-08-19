"""Parsing Deepgram's response shapes.

These are pure functions over real response payloads. Getting them wrong is
the kind of bug that produces a plausible-looking empty transcript, so they are
worth pinning down without a network call.
"""

from __future__ import annotations

import json

import pytest

from app.clients.stt.deepgram import _parse_batch_response, _parse_stream_message

BATCH_WITH_SPEAKERS = {
    "metadata": {"duration": 42.5, "model_info": {"name": "nova-2"}},
    "results": {
        "channels": [
            {
                "detected_language": "en",
                "alternatives": [{"transcript": "hello there how are you", "confidence": 0.97}],
            }
        ],
        "utterances": [
            {"speaker": 0, "transcript": "hello there", "start": 0.0, "end": 1.5},
            {"speaker": 1, "transcript": "how are you", "start": 1.6, "end": 3.0},
        ],
    },
}

BATCH_WITHOUT_SPEAKERS = {
    "metadata": {"duration": 8.0, "model_info": {"name": "nova-2"}},
    "results": {
        "channels": [{"alternatives": [{"transcript": "a single speaker here", "confidence": 0.9}]}]
    },
}


def test_speaker_turns_are_rendered_into_the_transcript():
    """Diarised text reads far better as a retrieved chunk than a flat wall."""
    result = _parse_batch_response(BATCH_WITH_SPEAKERS, "nova-2")

    assert result.text == "Speaker 0: hello there\nSpeaker 1: how are you"
    assert result.duration_seconds == 42.5
    assert result.language == "en"
    assert result.model == "nova-2"
    assert len(result.utterances) == 2
    assert result.utterances[0]["speaker"] == 0


def test_a_transcript_without_diarisation_falls_back_to_the_flat_alternative():
    result = _parse_batch_response(BATCH_WITHOUT_SPEAKERS, "nova-2")
    assert result.text == "a single speaker here"
    assert result.utterances == []
    assert result.confidence == 0.9


def test_an_empty_response_does_not_raise():
    """A malformed payload must produce an empty transcript, not a crash — the
    caller already treats empty as a reportable failure."""
    result = _parse_batch_response({}, "nova-2")
    assert result.text == ""
    assert result.duration_seconds is None


def test_utterances_with_no_text_are_skipped():
    payload = {
        "metadata": {},
        "results": {
            "channels": [{"alternatives": [{"transcript": "x"}]}],
            "utterances": [
                {"speaker": 0, "transcript": "", "start": 0, "end": 1},
                {"speaker": 0, "transcript": "real words", "start": 1, "end": 2},
            ],
        },
    }
    assert _parse_batch_response(payload, "nova-2").text == "Speaker 0: real words"


# --- streaming frames ------------------------------------------------------


def test_an_interim_frame_is_marked_not_final():
    """Interim segments are *replaced* by later ones; a consumer that appends
    every segment produces duplicated text."""
    frame = json.dumps(
        {
            "channel": {"alternatives": [{"transcript": "what is the", "confidence": 0.6}]},
            "is_final": False,
            "start": 0.0,
            "duration": 1.2,
        }
    )
    segment = _parse_stream_message(frame)
    assert segment is not None
    assert segment.text == "what is the"
    assert segment.is_final is False
    assert segment.end_seconds == pytest.approx(1.2)


def test_a_final_frame_is_marked_final():
    frame = json.dumps(
        {
            "channel": {
                "alternatives": [{"transcript": "what is the policy?", "confidence": 0.95}]
            },
            "is_final": True,
            "start": 0.0,
            "duration": 2.0,
        }
    )
    segment = _parse_stream_message(frame)
    assert segment is not None
    assert segment.is_final is True


@pytest.mark.parametrize(
    "frame",
    [
        "not json at all",
        json.dumps({"type": "Metadata", "request_id": "x"}),
        json.dumps({"channel": {"alternatives": []}}),
        json.dumps({"channel": {"alternatives": [{"transcript": ""}]}}),
        json.dumps({}),
    ],
)
def test_frames_carrying_no_transcript_are_ignored(frame):
    """Deepgram interleaves metadata and keepalive frames with results."""
    assert _parse_stream_message(frame) is None
