"""Voice: recorded audio in, retrievable transcript out.

A finished transcript is not a special kind of thing — it is a document. So
this service transcribes, writes the transcript to object storage as text, and
then hands it to the ordinary ingestion pipeline, which chunks and embeds it
exactly like an uploaded file. A meeting recording ends up answerable by the
same retrieval path as a PDF, with no separate code path to keep in sync.

The audio itself is kept alongside the transcript, so a recording can be
re-transcribed later (a better model, a corrected language hint) without asking
anyone to upload it again.
"""

from __future__ import annotations

import uuid

from app.clients.storage.base import StorageClient, build_storage_key
from app.clients.stt.base import TranscriptionClient
from app.core.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ProviderError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from app.core.logging import get_logger
from app.ingestion.detection import extension_of
from app.models.documents import Document
from app.models.enums import DocumentStatus, DocumentType, TranscriptStatus
from app.models.voice import VoiceRecording
from app.repositories.documents import DocumentRepository
from app.repositories.voice import VoiceRecordingRepository
from app.schemas.voice import VoiceRecordingResponse

log = get_logger(__name__)

# Container formats Deepgram accepts, mapped to the media type it expects.
AUDIO_MEDIA_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


class VoiceService:
    def __init__(
        self,
        *,
        recordings: VoiceRecordingRepository,
        documents: DocumentRepository,
        storage: StorageClient,
        transcriber: TranscriptionClient | None,
        max_audio_bytes: int,
    ) -> None:
        self._recordings = recordings
        self._documents = documents
        self._storage = storage
        self._transcriber = transcriber
        self._max_audio_bytes = max_audio_bytes

    def _require_transcriber(self) -> TranscriptionClient:
        if self._transcriber is None:
            raise ProviderError(
                "Voice transcription is not configured. Set DEEPGRAM_API_KEY and "
                "STT_PROVIDER=deepgram to enable it."
            )
        return self._transcriber

    async def upload(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> VoiceRecordingResponse:
        """Store a recording and queue it for transcription."""
        self._require_transcriber()

        if not data:
            raise ValidationError("The uploaded recording is empty.")
        if len(data) > self._max_audio_bytes:
            limit_mb = self._max_audio_bytes // (1024 * 1024)
            raise PayloadTooLargeError(f"Recordings must be {limit_mb}MB or smaller.")

        extension = extension_of(filename)
        if extension not in AUDIO_MEDIA_TYPES:
            raise UnsupportedMediaTypeError(
                f"'{extension or filename}' is not a supported audio format. "
                f"Supported: {', '.join(sorted(AUDIO_MEDIA_TYPES))}."
            )

        recording_id = uuid.uuid4()
        storage_key = build_storage_key(workspace_id, "recordings", str(recording_id), filename)
        await self._storage.put(storage_key, data, content_type=AUDIO_MEDIA_TYPES[extension])

        recording = await self._recordings.add(
            VoiceRecording(
                id=recording_id,
                workspace_id=workspace_id,
                uploaded_by=user_id,
                storage_path=storage_key,
                transcript_status=TranscriptStatus.PENDING,
            )
        )
        await self._recordings.commit()

        log.info(
            "voice_recording_uploaded",
            recording_id=str(recording.id),
            workspace_id=str(workspace_id),
            size_bytes=len(data),
        )
        return VoiceRecordingResponse.model_validate(recording)

    async def transcribe(self, recording_id: uuid.UUID, workspace_id: uuid.UUID) -> Document | None:
        """Transcribe a stored recording and create its document.

        Returns the created document so the caller can run ingestion on it.
        Failures are recorded on the recording rather than raised: this runs in
        a worker, and a user needs to see why a recording failed rather than
        lose it to a traceback.
        """
        recording = await self._recordings.get_scoped(recording_id, workspace_id)
        if recording is None:
            log.warning("voice_recording_missing", recording_id=str(recording_id))
            return None

        transcriber = self._require_transcriber()

        try:
            recording.transcript_status = TranscriptStatus.PROCESSING
            await self._recordings.commit()

            audio = await self._storage.get(recording.storage_path)
            extension = extension_of(recording.storage_path)
            transcription = await transcriber.transcribe(
                audio, content_type=AUDIO_MEDIA_TYPES.get(extension, "audio/webm")
            )

            if not transcription.text.strip():
                raise ValidationError("No speech was detected in this recording.")

            document = await self._create_transcript_document(recording, transcription)

            recording.transcript = transcription.text
            recording.duration_seconds = transcription.duration_seconds
            recording.document_id = document.id
            recording.transcript_status = TranscriptStatus.READY
            recording.error_message = None
            await self._recordings.commit()

            log.info(
                "voice_recording_transcribed",
                recording_id=str(recording.id),
                document_id=str(document.id),
                duration=transcription.duration_seconds,
                characters=len(transcription.text),
            )
            return document

        except Exception as exc:
            detail = (
                str(exc)
                if isinstance(exc, ValidationError | ProviderError)
                else "Transcription failed."
            )
            log.exception("voice_transcription_failed", recording_id=str(recording_id))
            recording.transcript_status = TranscriptStatus.FAILED
            recording.error_message = detail
            await self._recordings.commit()
            return None

    async def _create_transcript_document(
        self, recording: VoiceRecording, transcription
    ) -> Document:
        """Write the transcript as a document so ingestion can pick it up.

        The document's stored object *is* the transcript text, which is why
        `DocumentType.AUDIO` parses as plain text — the audio stays referenced
        in metadata rather than being what gets parsed.
        """
        import hashlib

        text_bytes = transcription.text.encode("utf-8")
        original_name = recording.storage_path.rsplit("/", 1)[-1]
        transcript_name = f"{original_name.rsplit('.', 1)[0]} (transcript).txt"

        document_id = uuid.uuid4()
        storage_key = build_storage_key(
            recording.workspace_id, "documents", str(document_id), transcript_name
        )
        await self._storage.put(storage_key, text_bytes, content_type="text/plain")

        document = await self._documents.add(
            Document(
                id=document_id,
                workspace_id=recording.workspace_id,
                uploaded_by=recording.uploaded_by,
                filename=transcript_name,
                content_type="text/plain",
                doc_type=DocumentType.AUDIO,
                size_bytes=len(text_bytes),
                storage_key=storage_key,
                checksum_sha256=hashlib.sha256(text_bytes).hexdigest(),
                status=DocumentStatus.PENDING,
                doc_metadata={
                    "source": "voice",
                    "recording_id": str(recording.id),
                    "audio_key": recording.storage_path,
                    "duration_seconds": transcription.duration_seconds,
                    "stt_model": transcription.model,
                    "language": transcription.language,
                    "speaker_count": len(
                        {
                            u["speaker"]
                            for u in transcription.utterances
                            if u.get("speaker") is not None
                        }
                    ),
                },
            )
        )
        await self._documents.commit()
        return document

    async def get(self, recording_id: uuid.UUID, workspace_id: uuid.UUID) -> VoiceRecordingResponse:
        recording = await self._recordings.get_scoped(recording_id, workspace_id)
        if recording is None:
            raise NotFoundError("Recording not found.")
        return VoiceRecordingResponse.model_validate(recording)

    async def list(self, workspace_id: uuid.UUID) -> list[VoiceRecordingResponse]:
        rows = await self._recordings.list_for_workspace(workspace_id)
        return [VoiceRecordingResponse.model_validate(r) for r in rows]

    async def delete(self, recording_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        recording = await self._recordings.get_scoped(recording_id, workspace_id)
        if recording is None:
            raise NotFoundError("Recording not found.")

        # The audio object goes; the transcript document stays. Deleting the
        # recording should not silently remove knowledge the team has been
        # building on — that document is deletable on its own terms.
        await self._storage.delete(recording.storage_path)
        await self._recordings.delete(recording)
        await self._recordings.commit()
        log.info("voice_recording_deleted", recording_id=str(recording_id))
