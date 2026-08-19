"""Embedding provider contract.

Every implementation emits vectors of exactly `dim` dimensions, because the
`document_chunks.embedding` column has a fixed width chosen at migration time.
Providers that support a native dimension parameter are configured to match;
none of them are truncated or padded after the fact, which would silently
distort distances.
"""

from __future__ import annotations

import abc
from typing import Literal

InputKind = Literal["document", "query"]


class EmbeddingProvider(abc.ABC):
    name: str
    dim: int

    @abc.abstractmethod
    async def embed(self, texts: list[str], *, kind: InputKind = "document") -> list[list[float]]:
        """Embed a batch.

        `kind` matters for providers with asymmetric document/query encodings —
        embedding a question with the document encoding measurably degrades
        retrieval.
        """

    async def embed_one(self, text: str, *, kind: InputKind = "document") -> list[float]:
        result = await self.embed([text], kind=kind)
        return result[0]
