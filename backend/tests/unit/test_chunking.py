"""Chunking behaviour."""

from __future__ import annotations

from app.ingestion.chunking import (
    DEFAULT_CHUNK_SIZE,
    chunk_blocks,
    estimate_tokens,
    normalise,
    split_text,
)
from app.ingestion.types import TextBlock


def test_short_text_is_one_chunk():
    assert split_text("A short sentence.") == ["A short sentence."]


def test_empty_text_produces_no_chunks():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_long_text_splits_into_multiple_chunks():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_chunks_respect_the_size_budget():
    text = "word " * 4000
    chunks = split_text(text, chunk_size=400, overlap=40)
    # Overlap is prepended to the next chunk, so a chunk can exceed the target
    # by up to the overlap — but not by more.
    assert all(len(chunk) <= 400 + 40 for chunk in chunks)


def test_overlap_carries_context_across_the_seam():
    text = "\n\n".join(f"Distinct paragraph number {i}." for i in range(40))
    with_overlap = split_text(text, chunk_size=300, overlap=80)
    without_overlap = split_text(text, chunk_size=300, overlap=0)
    # Repeating content across boundaries necessarily produces more total text.
    assert sum(map(len, with_overlap)) > sum(map(len, without_overlap))


def test_split_prefers_paragraph_boundaries():
    text = "First paragraph here.\n\n" + "x" * 200 + "\n\nThird paragraph."
    chunks = split_text(text, chunk_size=100, overlap=0)
    assert chunks[0].startswith("First paragraph here.")


def test_no_content_is_lost_when_overlap_is_zero():
    text = " ".join(f"token{i}" for i in range(2000))
    chunks = split_text(text, chunk_size=500, overlap=0)
    rejoined = " ".join(chunks)
    for marker in ("token0", "token999", "token1999"):
        assert marker in rejoined


def test_tiny_trailing_fragment_is_merged():
    text = "x" * 1000 + "\n\nend."
    chunks = split_text(text, chunk_size=1000, overlap=0)
    assert not any(len(c) < 20 for c in chunks)


def test_normalise_collapses_whitespace_but_keeps_paragraphs():
    assert normalise("a    b\n\n\n\nc") == "a b\n\nc"
    assert normalise("line\r\nline") == "line\nline"


def test_chunk_blocks_carries_provenance_metadata():
    blocks = [
        TextBlock(content="short one", metadata={"page": 3}),
        TextBlock(content="word " * 2000, metadata={"page": 4}),
    ]
    pieces = chunk_blocks(blocks, chunk_size=DEFAULT_CHUNK_SIZE, overlap=100)

    assert pieces[0].metadata["page"] == 3
    # Every piece of a split block keeps the source page and gains part markers.
    page_four = [p for p in pieces if p.metadata["page"] == 4]
    assert len(page_four) > 1
    assert all("part" in p.metadata for p in page_four)
    assert page_four[0].metadata["part_count"] == len(page_four)


def test_estimate_tokens_is_never_zero():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 100
