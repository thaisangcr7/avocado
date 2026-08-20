"""Conversations: creating threads, and running a turn through RAG."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from app.clients.llm.base import ChatMessage as LLMMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.core.errors import AvocadoError, NotFoundError
from app.core.logging import get_logger
from app.models.conversations import Conversation, Message
from app.models.enums import MessageRole
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.schemas.chat import (
    ChatTurnResponse,
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)
from app.services.rag_service import SYSTEM_PROMPT, RAGService
from app.services.usage_service import UsageService

log = get_logger(__name__)

# How many prior messages travel with a turn. Enough for follow-ups ("what
# about the other region?") without resending an entire thread every time.
HISTORY_WINDOW = 10

TITLE_PROMPT = (
    "Write a title of at most six words for a conversation that starts with "
    "the message below. Reply with the title only — no quotes, no punctuation "
    "at the end.\n\n"
)


class ChatService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        rag: RAGService,
        router: ModelRouter,
        usage: UsageService,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._rag = rag
        self._router = router
        self._usage = usage

    async def create(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, payload: ConversationCreate
    ) -> ConversationResponse:
        conversation = await self._conversations.add(
            Conversation(
                workspace_id=workspace_id,
                user_id=user_id,
                task_id=payload.task_id,
                title=payload.title or "New conversation",
            )
        )
        await self._conversations.commit()
        return ConversationResponse.model_validate(conversation)

    async def list(self, workspace_id: uuid.UUID) -> list[ConversationResponse]:
        rows = await self._conversations.list_for_workspace(workspace_id)
        return [ConversationResponse.model_validate(c) for c in rows]

    async def get(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> ConversationResponse:
        conversation = await self._require(conversation_id, workspace_id)
        return ConversationResponse.model_validate(conversation)

    async def rename(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID, title: str
    ) -> ConversationResponse:
        conversation = await self._require(conversation_id, workspace_id)
        conversation.title = title
        await self._conversations.commit()
        await self._conversations.refresh(conversation)
        return ConversationResponse.model_validate(conversation)

    async def delete(self, conversation_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        conversation = await self._require(conversation_id, workspace_id)
        await self._conversations.delete(conversation)
        await self._conversations.commit()

    async def messages(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[MessageResponse]:
        await self._require(conversation_id, workspace_id)
        rows = await self._messages.list_for_conversation(conversation_id, workspace_id)
        return [MessageResponse.model_validate(m) for m in rows]

    async def send(
        self,
        *,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        preferred_model: str | None,
        payload: MessageCreate,
    ) -> ChatTurnResponse:
        conversation = await self._require(conversation_id, workspace_id)
        history = await self._messages.recent_history(
            conversation_id, workspace_id, limit=HISTORY_WINDOW
        )

        user_message = await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.USER,
                content=payload.content,
            )
        )
        await self._messages.commit()

        try:
            (
                answer,
                citations,
                model_used,
                in_tokens,
                out_tokens,
                latency_ms,
            ) = await self._rag.answer(
                workspace_id=workspace_id,
                question=payload.content,
                history=history,
                preferred_model=preferred_model,
                document_ids=payload.document_ids or None,
            )
        except AvocadoError as exc:
            # The user's turn genuinely happened, so the question stays in the
            # thread. Record the failure beside it, or a reload shows a
            # question with no reply and no explanation once the transient
            # error notice is gone.
            await self._record_failure(conversation_id, workspace_id, exc.detail)
            raise

        assistant_message = await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                citations=[c.model_dump(mode="json") for c in citations],
                model_used=model_used,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                latency_ms=latency_ms,
            )
        )

        # First real exchange: give the thread a title so the sidebar is
        # readable without the user having to name anything.
        if not history and conversation.title == "New conversation":
            conversation.title = await self._suggest_title(payload.content)

        await self._messages.commit()

        await self._usage.record(
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            endpoint="messages.create",
            model=model_used,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=latency_ms,
        )

        return ChatTurnResponse(
            user_message=MessageResponse.model_validate(user_message),
            assistant_message=MessageResponse.model_validate(assistant_message),
        )

    async def _record_failure(
        self, conversation_id: uuid.UUID, workspace_id: uuid.UUID, detail: str
    ) -> None:
        await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.ASSISTANT,
                content=detail,
                failed=True,
            )
        )
        await self._messages.commit()

    async def stream(
        self,
        *,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        preferred_model: str | None,
        payload: MessageCreate,
    ) -> AsyncIterator[dict]:
        """Run a turn, emitting SSE-shaped events as the answer is produced.

        Events: `citations` (once, before any text, so sources render
        immediately), then `token` repeatedly, then `done`.
        """
        await self._require(conversation_id, workspace_id)
        history = await self._messages.recent_history(
            conversation_id, workspace_id, limit=HISTORY_WINDOW
        )

        await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.USER,
                content=payload.content,
            )
        )
        await self._messages.commit()

        hits = await self._rag.retrieve(
            workspace_id=workspace_id,
            question=payload.content,
            document_ids=payload.document_ids or None,
        )
        provider, spec = self._router.resolve(
            task=TaskType.SYNTHESIS, preferred_model=preferred_model
        )

        if not hits:
            text = "I could not find anything in this workspace's documents that " "answers that."
            yield {"event": "token", "data": {"text": text}}
            await self._finish_stream(
                conversation_id, workspace_id, org_id, user_id, text, [], spec.id, 0, 0, 0
            )
            yield {"event": "done", "data": {"model": spec.id, "citations": []}}
            return

        # Sources are sent up front: the reader can start checking them while
        # the answer is still being written.
        preliminary = [
            {
                "index": i + 1,
                "document_id": str(chunk.document_id),
                "document_name": filename,
                "score": round(score, 4),
            }
            for i, (chunk, score, filename) in enumerate(hits)
        ]
        yield {"event": "citations", "data": {"sources": preliminary}}

        context = self._rag.build_context(hits)
        messages = [
            LLMMessage(
                role="user" if m.role is MessageRole.USER else "assistant",
                content=m.content,
            )
            for m in history
        ]
        messages.append(
            LLMMessage(
                role="user",
                content=f"Sources:\n\n{context}\n\n---\n\nQuestion: {payload.content}",
            )
        )

        collected: list[str] = []
        usage_in = usage_out = 0
        model_used = spec.id
        async for chunk_event in provider.stream(
            messages=messages,
            model=spec.id,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
        ):
            if chunk_event.done:
                model_used = chunk_event.model or spec.id
                if chunk_event.usage:
                    usage_in = chunk_event.usage.input_tokens
                    usage_out = chunk_event.usage.output_tokens
                break
            if chunk_event.text:
                collected.append(chunk_event.text)
                yield {"event": "token", "data": {"text": chunk_event.text}}

        answer = "".join(collected)
        citations = self._rag.citations_for(answer, hits)
        await self._finish_stream(
            conversation_id,
            workspace_id,
            org_id,
            user_id,
            answer,
            citations,
            model_used,
            usage_in,
            usage_out,
            0,
        )
        yield {
            "event": "done",
            "data": {
                "model": model_used,
                "citations": [c.model_dump(mode="json") for c in citations],
            },
        }

    async def _finish_stream(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        answer: str,
        citations: list,
        model_used: str | None,
        in_tokens: int,
        out_tokens: int,
        latency_ms: int,
    ) -> None:
        await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                citations=[c.model_dump(mode="json") for c in citations],
                model_used=model_used,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                latency_ms=latency_ms,
            )
        )
        await self._messages.commit()
        await self._usage.record(
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            endpoint="messages.stream",
            model=model_used,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=latency_ms,
        )

    async def _suggest_title(self, first_message: str) -> str:
        """Name a thread from its opening message.

        A cheap model on a trivial task — and a failure here must never cost
        the user their answer, so it falls back to a truncation.
        """
        try:
            provider, spec = self._router.resolve(task=TaskType.TITLE)
            result = await provider.generate(
                messages=[LLMMessage(role="user", content=TITLE_PROMPT + first_message[:500])],
                model=spec.id,
                max_tokens=32,
            )
            title = result.text.strip().strip('"').strip()
            if title:
                return title[:300]
        except Exception:
            log.debug("title_generation_failed", exc_info=True)
        return first_message[:60].strip() or "New conversation"

    async def _require(self, conversation_id: uuid.UUID, workspace_id: uuid.UUID) -> Conversation:
        conversation = await self._conversations.get_scoped(conversation_id, workspace_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation
