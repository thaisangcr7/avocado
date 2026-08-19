"""Shared shapes produced by parsing, consumed by chunking and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class TextBlock:
    """A contiguous run of text plus where it came from.

    `metadata` is what a citation is rendered from — page number, sheet name,
    section heading — so it travels with the text all the way to the chunk row.
    """

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedColumn:
    name: str
    dtype: str
    null_count: int = 0
    sample_values: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "null_count": self.null_count,
            "sample_values": self.sample_values,
        }


@dataclass(slots=True)
class ParsedTable:
    """A sheet in structured form, ready for the analysis engine."""

    name: str
    sheet_index: int
    columns: list[ParsedColumn]
    row_count: int
    csv_bytes: bytes  # Normalised CSV — one format for the sandbox to load.


@dataclass(slots=True)
class ParsedDocument:
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int | None = None


class VisionExtractor(Protocol):
    """Describes an image well enough to retrieve and cite it.

    Injected rather than imported so parsers stay free of LLM clients and can
    be unit-tested without a network.
    """

    async def __call__(self, *, data: bytes, media_type: str, filename: str) -> str: ...
