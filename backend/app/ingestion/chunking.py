"""Splitting parsed text into embeddable chunks.

Chunk boundaries are chosen on the largest natural separator that fits —
paragraph, then line, then sentence, then whitespace — so a chunk rarely ends
mid-thought. Overlap carries a little context across the seam, which is what
keeps an answer coherent when the relevant passage straddles a boundary.

Sizes are in characters, not tokens: this runs on every uploaded document, and
a tokeniser call per chunk is a real cost for an approximation that only feeds
a rough token estimate. `estimate_tokens` is explicitly an estimate.
"""

from __future__ import annotations

import re

from app.ingestion.types import TextBlock

DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 150
MIN_CHUNK_SIZE = 80

# Ordered widest-to-narrowest; the first separator that yields a usable split
# wins.
_SEPARATORS = ["\n\n", "\n", ". ", " "]

_WHITESPACE_RE = re.compile(r"[ \t]+")


def normalise(text: str) -> str:
    """Collapse runs of spaces and blank lines without losing paragraphing."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def estimate_tokens(text: str) -> int:
    """Rough token count — about four characters per token for English prose."""
    return max(1, len(text) // 4)


def _split_once(text: str, size: int) -> tuple[str, str]:
    """Take up to `size` characters, cutting at the widest separator available."""
    if len(text) <= size:
        return text, ""

    window = text[:size]
    for separator in _SEPARATORS:
        cut = window.rfind(separator)
        # Refuse a cut so early that the chunk is mostly empty — better to
        # split at a narrower separator, or mid-word as a last resort.
        if cut > size // 3:
            end = cut + len(separator)
            return text[:end], text[end:]
    return window, text[size:]


def split_text(
    text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    text = normalise(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    remainder = text
    while remainder:
        chunk, remainder = _split_once(remainder, chunk_size)
        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)
        if not remainder:
            break
        # Re-attach the tail of this chunk to the front of the next one.
        if overlap > 0 and chunks:
            carry = chunks[-1][-overlap:]
            remainder = carry + remainder

    # A short trailing fragment reads better merged into its predecessor than
    # standing alone as a near-contentless chunk.
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK_SIZE:
        tail = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n{tail}"

    return chunks


def chunk_blocks(
    blocks: list[TextBlock],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[TextBlock]:
    """Chunk each block, carrying its provenance metadata onto every piece."""
    out: list[TextBlock] = []
    for block in blocks:
        pieces = split_text(block.content, chunk_size=chunk_size, overlap=overlap)
        for index, piece in enumerate(pieces):
            metadata = dict(block.metadata)
            if len(pieces) > 1:
                metadata["part"] = index + 1
                metadata["part_count"] = len(pieces)
            out.append(TextBlock(content=piece, metadata=metadata))
    return out
