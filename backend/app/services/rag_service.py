"""Retrieval-augmented question answering with citations.

    embed question -> nearest chunks in this workspace -> grounded answer

Two decisions worth stating, because both are easy to get subtly wrong:

* The question is embedded with the *query* encoding, not the document one.
  Providers with asymmetric encoders lose measurable retrieval quality when a
  question is embedded as though it were a passage.

* Retrieved passages are numbered, and the model is instructed to cite those
  numbers. Only the sources it actually cites are attached to the message, so a
  citation list is evidence the answer used a source rather than a list of
  everything that happened to be retrieved.
"""

from __future__ import annotations

import re
import time
import uuid

from app.clients.embeddings.base import EmbeddingProvider
from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.core.errors import ProviderError, ValidationError
from app.core.logging import get_logger
from app.models.conversations import Message
from app.models.documents import DocumentChunk
from app.models.enums import MessageRole
from app.repositories.documents import ChunkRepository
from app.schemas.chat import Citation

log = get_logger(__name__)

DEFAULT_TOP_K = 8

# Below this cosine similarity a passage is more likely noise than context.
# Deliberately permissive: the answer prompt is what handles weak evidence,
# and cutting too aggressively here produces confident "I don't know"s on
# questions the corpus can actually answer.
MIN_SIMILARITY = 0.15

SYSTEM_PROMPT = """You are Avocado, a knowledge assistant for a team's own documents.

Answer only from the numbered sources provided. They are the entire basis for \
your answer.

Rules:
- Cite the source number inline as [1], [2] immediately after each claim it \
supports.
- Never fill gaps with general knowledge.
- If sources are partial but contain relevant evidence, still provide the most \
useful provisional answer from those sources, then add a brief "Limits" \
section listing exactly what is missing.
- Only say the answer cannot be produced when there is effectively no relevant \
evidence in the provided sources.
- If sources disagree, say so and cite both rather than silently picking one.
- Quote exact figures, dates, and names from the sources; do not round or \
paraphrase numbers.
- Lead with the answer in the first sentence. No preamble.
- Match the shape of the response to the question: one short paragraph for a \
simple fact; clear headings and bullets for comparisons, summaries, procedures, \
or multi-part questions.
- For requests like "executive summary", "KPI report", or "dashboard \
narrative", return that structure directly using only cited evidence from the \
sources. If coverage is incomplete, keep the requested structure and include \
"Limits" rather than refusing.
- Surface the most decision-useful details first. When several facts matter, \
group them by theme instead of producing one dense paragraph.
- Use Markdown sparingly for readability. Do not add a generic "Summary" \
heading, repeat the question, or end with an offer to help.

Earlier turns in this conversation were answered from their own sources, which \
are retrieved fresh for every question and are not shown to you again. Treat \
those answers as already grounded: do not re-check, retract, or correct them \
against the sources below, and do not remark on their absence. The numbered \
sources below belong to the current question only — the same number meant a \
different source in an earlier turn."""

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")

# Reached only when retrieval found nothing. The message is either not about
# the documents at all — a greeting, a question about what this thing does — or
# it is a content question the workspace cannot answer. Those two deserve very
# different replies, and answering both with "nothing matched" is what makes a
# greeting feel like talking to a search box.
UNGROUNDED_PROMPT = """You are Avocado, an assistant that answers questions about \
a team's own documents.

Nothing in the user's workspace matched their message. Decide which of these it is:

- A greeting, thanks, or small talk — reply briefly and naturally, and say what \
you can do with their documents.
- A question about you, your abilities, or how to use this — answer it directly.
- Anything that would need their documents to answer — say plainly that nothing \
in this workspace covers it, and suggest what they could upload. Never answer \
such a question from general knowledge, and never invent what a document says.

Be brief. No preamble."""

NO_RESULTS_ANSWER = (
    "I could not find anything in this workspace's documents that answers that. "
    "If you expected a match, the source may still be processing, or it may not "
    "have been uploaded yet."
)


class RAGService:
    def __init__(
        self,
        *,
        chunks: ChunkRepository,
        embeddings: EmbeddingProvider,
        router: ModelRouter,
    ) -> None:
        self._chunks = chunks
        self._embeddings = embeddings
        self._router = router

    async def retrieve(
        self,
        *,
        workspace_id: uuid.UUID,
        question: str,
        top_k: int = DEFAULT_TOP_K,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[DocumentChunk, float, str]]:
        vector = await self._embeddings.embed_one(question, kind="query")
        hits = await self._chunks.search(
            workspace_id=workspace_id,
            embedding=vector,
            embedding_model=self._embeddings.signature,
            limit=top_k,
            document_ids=document_ids,
        )
        return [hit for hit in hits if hit[1] >= MIN_SIMILARITY]

    @staticmethod
    def build_context(hits: list[tuple[DocumentChunk, float, str]]) -> str:
        """Render retrieved passages as the numbered source list the prompt cites."""
        parts: list[str] = []
        for index, (chunk, _score, filename) in enumerate(hits, start=1):
            location = _describe_location(chunk)
            header = f"[{index}] {filename}" + (f" ({location})" if location else "")
            parts.append(f"{header}\n{chunk.content}")
        return "\n\n---\n\n".join(parts)

    async def _answer_ungrounded(
        self,
        *,
        question: str,
        history: list[Message],
        preferred_model: str | None,
    ) -> tuple[str, list[Citation], str | None, int, int, int]:
        """Reply when retrieval found nothing to ground an answer in.

        "Hello" and "what is our refund policy" both retrieve nothing, and only
        one of them deserves to be told the workspace has no match. The model
        decides which it is, under a prompt that forbids answering a content
        question from general knowledge — the honesty guarantee has to survive
        the friendlier greeting.

        Falls back to the plain no-results line when no provider is configured,
        so a deployment without a key still answers rather than failing.
        """
        try:
            provider, spec = self._router.resolve(
                task=TaskType.SUMMARIZATION, preferred_model=preferred_model
            )
        except (ProviderError, ValidationError):
            return (NO_RESULTS_ANSWER, [], None, 0, 0, 0)

        started = time.perf_counter()
        messages = [
            ChatMessage(
                role="user" if m.role is MessageRole.USER else "assistant",
                content=m.content,
            )
            for m in history
        ]
        messages.append(ChatMessage(role="user", content=question))

        try:
            result = await provider.generate(
                messages=messages,
                model=spec.id,
                system=UNGROUNDED_PROMPT,
                max_tokens=600,
            )
        except ProviderError:
            return (NO_RESULTS_ANSWER, [], None, 0, 0, 0)

        log.info("rag_answered_ungrounded", model=result.model)
        return (
            result.text,
            [],
            result.model,
            result.usage.input_tokens,
            result.usage.output_tokens,
            int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def citations_for(answer: str, hits: list[tuple[DocumentChunk, float, str]]) -> list[Citation]:
        """Return only the sources the answer actually cited.

        Indices outside the retrieved range are ignored rather than trusted —
        a model can emit [9] when eight sources were supplied.
        """
        cited = {int(n) for n in _CITATION_RE.findall(answer) if 1 <= int(n) <= len(hits)}
        out: list[Citation] = []
        for index in sorted(cited):
            chunk, score, filename = hits[index - 1]
            metadata = chunk.chunk_metadata or {}
            out.append(
                Citation(
                    document_id=chunk.document_id,
                    document_name=filename,
                    chunk_id=chunk.id,
                    snippet=chunk.content[:400],
                    score=round(score, 4),
                    page=metadata.get("page"),
                    sheet=metadata.get("sheet"),
                    section=metadata.get("section"),
                )
            )
        return out

    async def answer(
        self,
        *,
        workspace_id: uuid.UUID,
        question: str,
        history: list[Message],
        preferred_model: str | None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> tuple[str, list[Citation], str | None, int, int, int]:
        """Answer a question. Returns (text, citations, model, in, out, ms).

        `model` is None when no model was involved — an empty retrieval is
        answered directly.
        """
        hits = await self.retrieve(
            workspace_id=workspace_id, question=question, document_ids=document_ids
        )

        if not hits:
            return await self._answer_ungrounded(
                question=question, history=history, preferred_model=preferred_model
            )

        provider, spec = self._router.resolve(
            task=TaskType.SYNTHESIS, preferred_model=preferred_model
        )

        context = self.build_context(hits)
        messages = [
            ChatMessage(
                role="user" if m.role is MessageRole.USER else "assistant",
                content=m.content,
            )
            for m in history
        ]
        messages.append(
            ChatMessage(
                role="user",
                content=f"Sources:\n\n{context}\n\n---\n\nQuestion: {question}",
            )
        )

        result = await provider.generate(
            messages=messages,
            model=spec.id,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
        )

        citations = self.citations_for(result.text, hits)
        log.info(
            "rag_answered",
            workspace_id=str(workspace_id),
            retrieved=len(hits),
            cited=len(citations),
            model=result.model,
        )
        return (
            result.text,
            citations,
            result.model,
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.latency_ms,
        )


def _describe_location(chunk: DocumentChunk) -> str:
    """Human-readable provenance for a chunk, used in the source header."""
    metadata = chunk.chunk_metadata or {}
    parts: list[str] = []
    if page := metadata.get("page"):
        parts.append(f"page {page}")
    if sheet := metadata.get("sheet"):
        parts.append(f"sheet '{sheet}'")
    if section := metadata.get("section"):
        parts.append(f"section '{section}'")
    if metadata.get("source") == "vision":
        parts.append("image description")
    return ", ".join(parts)
