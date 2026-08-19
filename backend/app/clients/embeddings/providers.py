"""Embedding implementations: Voyage, OpenAI, and a deterministic dev stand-in."""

from __future__ import annotations

import hashlib
import math
import re

import httpx
import openai

from app.clients.embeddings.base import EmbeddingProvider, InputKind
from app.core.config import Settings
from app.core.errors import ProviderError, ValidationError

_MAX_BATCH = 96


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI — Anthropic's recommended embedding partner.

    `voyage-3` is natively 1024-dimensional, matching the default column width.
    """

    name = "voyage"

    def __init__(self, api_key: str, model: str = "voyage-3", dim: int = 1024) -> None:
        self._api_key = api_key
        self._model = model
        self.dim = dim

    async def embed(self, texts: list[str], *, kind: InputKind = "document") -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for start in range(0, len(texts), _MAX_BATCH):
                batch = texts[start : start + _MAX_BATCH]
                try:
                    response = await client.post(
                        "https://api.voyageai.com/v1/embeddings",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={
                            "input": batch,
                            "model": self._model,
                            "input_type": "query" if kind == "query" else "document",
                            "output_dimension": self.dim,
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise ProviderError("Voyage embedding request failed.") from exc

                data = response.json()["data"]
                out.extend(item["embedding"] for item in sorted(data, key=lambda d: d["index"]))
        return out


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings.

    `text-embedding-3-*` accepts a `dimensions` parameter, so it can emit the
    configured width natively rather than being reshaped afterwards.
    """

    name = "openai"

    def __init__(
        self, api_key: str, model: str = "text-embedding-3-small", dim: int = 1024
    ) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=60.0)
        self._model = model
        self.dim = dim

    async def embed(self, texts: list[str], *, kind: InputKind = "document") -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), _MAX_BATCH):
            batch = texts[start : start + _MAX_BATCH]
            try:
                response = await self._client.embeddings.create(
                    model=self._model, input=batch, dimensions=self.dim
                )
            except openai.APIError as exc:
                raise ProviderError("OpenAI embedding request failed.") from exc
            out.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return out


_TOKEN_RE = re.compile(r"[a-z0-9']+")


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic offline embeddings — development and tests only.

    A hashed bag-of-words projection. It carries real lexical signal (documents
    sharing vocabulary land near each other), which is enough to exercise the
    whole retrieval path end to end without a network call or an API key. It is
    emphatically not semantic: config rejects it outside development so it can
    never quietly serve production traffic.
    """

    name = "hash"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            # A zero vector has undefined cosine distance; a fixed unit vector
            # keeps the maths well-defined for empty input.
            vec[0] = 1.0
            return vec

        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            # Sign from an independent byte so unrelated tokens can cancel
            # rather than always accumulating.
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    async def embed(self, texts: list[str], *, kind: InputKind = "document") -> list[list[float]]:
        return [self._vector(t) for t in texts]


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    dim = settings.embedding_dim
    match settings.embedding_provider:
        case "voyage":
            if not settings.voyage_api_key:
                raise ProviderError("VOYAGE_API_KEY is not configured.")
            return VoyageEmbeddingProvider(settings.voyage_api_key, settings.voyage_model, dim)
        case "openai":
            if not settings.openai_api_key:
                raise ProviderError("OPENAI_API_KEY is not configured.")
            return OpenAIEmbeddingProvider(
                settings.openai_api_key, settings.openai_embedding_model, dim
            )
        case "hash":
            return HashingEmbeddingProvider(dim)
        case _:
            raise ValidationError(f"Unknown embedding provider '{settings.embedding_provider}'.")
