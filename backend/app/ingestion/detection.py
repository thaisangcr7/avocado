"""Deciding what an upload actually is, and whether it is allowed.

The declared `Content-Type` is a client-supplied hint, so it is corroborated
against the file extension and, for the formats where it is cheap, the magic
bytes. A mismatch is rejected rather than guessed at: accepting a "text/csv"
that is really a zip is how a parser gets handed something it never expected.
"""

from __future__ import annotations

from app.core.errors import UnsupportedMediaTypeError
from app.models.enums import DocumentType

EXTENSION_TYPES: dict[str, DocumentType] = {
    "pdf": DocumentType.PDF,
    "docx": DocumentType.DOCX,
    "xlsx": DocumentType.XLSX,
    "xlsm": DocumentType.XLSX,
    "csv": DocumentType.CSV,
    "tsv": DocumentType.CSV,
    "txt": DocumentType.TEXT,
    "log": DocumentType.TEXT,
    "md": DocumentType.MARKDOWN,
    "markdown": DocumentType.MARKDOWN,
    "png": DocumentType.IMAGE,
    "jpg": DocumentType.IMAGE,
    "jpeg": DocumentType.IMAGE,
    "gif": DocumentType.IMAGE,
    "webp": DocumentType.IMAGE,
    "mp3": DocumentType.AUDIO,
    "wav": DocumentType.AUDIO,
    "m4a": DocumentType.AUDIO,
    "webm": DocumentType.AUDIO,
}

# Media types Claude accepts for vision input.
IMAGE_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

_MAGIC_PREFIXES: list[tuple[bytes, set[DocumentType]]] = [
    (b"%PDF-", {DocumentType.PDF}),
    # docx and xlsx are both zip containers, so the signature narrows to the
    # pair rather than to one type.
    (b"PK\x03\x04", {DocumentType.DOCX, DocumentType.XLSX}),
    (b"\x89PNG\r\n\x1a\n", {DocumentType.IMAGE}),
    (b"\xff\xd8\xff", {DocumentType.IMAGE}),
    (b"GIF87a", {DocumentType.IMAGE}),
    (b"GIF89a", {DocumentType.IMAGE}),
]


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def detect_document_type(filename: str, content_type: str, head: bytes) -> DocumentType:
    extension = extension_of(filename)
    doc_type = EXTENSION_TYPES.get(extension)
    if doc_type is None:
        raise UnsupportedMediaTypeError(
            f"'{extension or filename}' is not a supported file type. "
            f"Supported: {', '.join(sorted(set(EXTENSION_TYPES)))}."
        )

    for prefix, allowed in _MAGIC_PREFIXES:
        if head.startswith(prefix):
            if doc_type not in allowed:
                raise UnsupportedMediaTypeError(
                    f"'{filename}' does not contain {doc_type.value} data."
                )
            return doc_type

    # No signature matched. Text-ish formats have no magic bytes, so that is
    # expected; a binary format reaching here means the content is not what the
    # extension claims.
    if doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN, DocumentType.CSV):
        return doc_type
    if doc_type is DocumentType.AUDIO:
        return doc_type
    raise UnsupportedMediaTypeError(f"'{filename}' does not contain valid {extension} data.")


def image_media_type(filename: str) -> str:
    extension = extension_of(filename)
    media_type = IMAGE_MEDIA_TYPES.get(extension)
    if media_type is None:
        raise UnsupportedMediaTypeError(f"'{extension}' is not a supported image format.")
    return media_type
