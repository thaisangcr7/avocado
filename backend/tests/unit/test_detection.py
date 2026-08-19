"""Upload type detection — the check that runs before any parser sees bytes."""

from __future__ import annotations

import pytest

from app.core.errors import UnsupportedMediaTypeError
from app.ingestion.detection import detect_document_type, image_media_type
from app.models.enums import DocumentType

PDF_MAGIC = b"%PDF-1.7\n"
ZIP_MAGIC = b"PK\x03\x04"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff\xe0"


@pytest.mark.parametrize(
    ("filename", "content_type", "head", "expected"),
    [
        ("report.pdf", "application/pdf", PDF_MAGIC, DocumentType.PDF),
        ("notes.docx", "application/vnd.openxmlformats", ZIP_MAGIC, DocumentType.DOCX),
        ("data.xlsx", "application/vnd.openxmlformats", ZIP_MAGIC, DocumentType.XLSX),
        ("data.csv", "text/csv", b"a,b,c\n", DocumentType.CSV),
        ("notes.txt", "text/plain", b"hello", DocumentType.TEXT),
        ("readme.md", "text/markdown", b"# Title", DocumentType.MARKDOWN),
        ("chart.png", "image/png", PNG_MAGIC, DocumentType.IMAGE),
        ("photo.jpg", "image/jpeg", JPEG_MAGIC, DocumentType.IMAGE),
    ],
)
def test_supported_types_are_recognised(filename, content_type, head, expected):
    assert detect_document_type(filename, content_type, head) is expected


def test_an_unknown_extension_is_rejected():
    with pytest.raises(UnsupportedMediaTypeError):
        detect_document_type("virus.exe", "application/octet-stream", b"MZ\x90")


def test_content_that_contradicts_the_extension_is_rejected():
    """A PNG renamed to .pdf must not be handed to the PDF parser."""
    with pytest.raises(UnsupportedMediaTypeError):
        detect_document_type("fake.pdf", "application/pdf", PNG_MAGIC)


def test_a_zip_renamed_to_pdf_is_rejected():
    with pytest.raises(UnsupportedMediaTypeError):
        detect_document_type("fake.pdf", "application/pdf", ZIP_MAGIC)


def test_a_pdf_renamed_to_xlsx_is_rejected():
    with pytest.raises(UnsupportedMediaTypeError):
        detect_document_type("fake.xlsx", "application/vnd.ms-excel", PDF_MAGIC)


def test_office_formats_share_a_signature_and_are_told_apart_by_extension():
    """Both are zip containers, so only the extension distinguishes them."""
    assert detect_document_type("a.docx", "x", ZIP_MAGIC) is DocumentType.DOCX
    assert detect_document_type("a.xlsx", "x", ZIP_MAGIC) is DocumentType.XLSX


def test_text_formats_have_no_signature_and_are_accepted_on_extension():
    assert detect_document_type("x.txt", "text/plain", b"anything at all") is DocumentType.TEXT


def test_a_file_with_no_extension_is_rejected():
    with pytest.raises(UnsupportedMediaTypeError):
        detect_document_type("README", "text/plain", b"text")


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [("a.png", "image/png"), ("a.jpg", "image/jpeg"), ("a.webp", "image/webp")],
)
def test_image_media_types_map_correctly(filename, media_type):
    assert image_media_type(filename) == media_type


def test_an_unsupported_image_format_is_rejected():
    with pytest.raises(UnsupportedMediaTypeError):
        image_media_type("scan.tiff")
