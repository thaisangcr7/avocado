"""Conversations: creating threads, and running a turn through RAG."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator

from app.clients.llm.base import ChatMessage as LLMMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.clients.tools.registry import McpServers
from app.core.errors import AvocadoError, NotFoundError
from app.core.logging import get_logger
from app.models.conversations import Conversation, Message
from app.models.documents import Document
from app.models.enums import DocumentType, FeedbackRating, MessageRole, ToolKind
from app.models.presets import Preset
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.repositories.documents import DocumentRepository
from app.repositories.feedback import MessageFeedbackRepository
from app.repositories.tools import ConversationToolRepository
from app.schemas.chat import (
    ChatTurnResponse,
    ConversationCreate,
    ConversationPage,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)
from app.services.analysis_service import AnalysisService
from app.services.preset_service import PresetService
from app.services.rag_service import SYSTEM_PROMPT, RAGService, with_preset
from app.services.report_service import ReportService
from app.services.tool_catalogue import BY_SLUG, catalogue_for
from app.services.tool_runner import ToolRunner
from app.services.usage_service import UsageService

log = get_logger(__name__)

WEB_SEARCH_SLUG = "web-search"

# How many prior messages travel with a turn. Enough for follow-ups ("what
# about the other region?") without resending an entire thread every time.
HISTORY_WINDOW = 10

TITLE_PROMPT = (
    "Write a title of at most six words for a conversation that starts with "
    "the message below. Reply with the title only — no quotes, no punctuation "
    "at the end.\n\n"
)

ANALYSIS_INTENT = re.compile(
    r"\b("
    r"analy[sz]e|analysis|dashboard|chart|graph|plot|visuali[sz]e|trend|"
    r"forecast|correlation|distribution|outlier|variance|rank|strongest|weakest|"
    r"top|bottom|highest|lowest|average|median|percent|growth|change over time"
    r")\b",
    re.IGNORECASE,
)
# A whole-workspace executive report, distinct from a single-chart analysis.
# Strong phrasing ("executive summary", "KPI report") asks for a synthesis and
# routes to a report whenever there is any data. Weak phrasing ("dashboard")
# only becomes a report when there are several datasets to synthesise across —
# a lone spreadsheet is better served by single-file analysis.
STRONG_REPORT_INTENT = re.compile(
    r"\b("
    r"executive\s+summary|exec\s+summary|executive\s+report|executive\s+briefing|"
    r"kpi\s*report|board\s+report|business\s+review|company\s+overview"
    r")\b",
    re.IGNORECASE,
)
WEAK_REPORT_INTENT = re.compile(
    r"\b(dashboard|briefing|overview)\b",
    re.IGNORECASE,
)
ANALYZABLE_TYPES = {DocumentType.CSV, DocumentType.XLSX}


class ChatService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        documents: DocumentRepository,
        rag: RAGService,
        analysis: AnalysisService,
        report: ReportService,
        router: ModelRouter,
        usage: UsageService,
        tools: ConversationToolRepository | None = None,
        servers: McpServers | None = None,
        presets: PresetService | None = None,
        feedback: MessageFeedbackRepository | None = None,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._documents = documents
        self._tools = tools
        self._servers = servers
        self._presets = presets
        self._feedback = feedback
        self._rag = rag
        self._analysis = analysis
        self._report = report
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

    async def history(
        self,
        workspace_id: uuid.UUID,
        *,
        which: str = "all",
        search: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> ConversationPage:
        """A page of history, each row carrying its message count."""
        rows, total = await self._conversations.search(
            workspace_id, which=which, search=search, limit=limit, offset=offset
        )
        conversations = []
        for conversation, count in rows:
            response = ConversationResponse.model_validate(conversation)
            response.message_count = count
            conversations.append(response)
        return ConversationPage(
            conversations=conversations, total=total, limit=limit, offset=offset
        )

    async def set_flags(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        pinned: bool | None = None,
        archived: bool | None = None,
    ) -> ConversationResponse:
        """Pin or file away. Only what was sent is changed."""
        conversation = await self._require(conversation_id, workspace_id)
        if pinned is not None:
            conversation.pinned = pinned
        if archived is not None:
            conversation.archived = archived
        await self._conversations.commit()
        await self._conversations.refresh(conversation)
        return ConversationResponse.model_validate(conversation)

    async def export(self, conversation_id: uuid.UUID, workspace_id: uuid.UUID) -> tuple[str, str]:
        """The whole thread as markdown. Returns (filename, body).

        Markdown rather than the API's own JSON because the point of an export
        is to be readable somewhere else — pasted into a document, attached to
        a ticket. Citations come with it, since an answer without its sources
        is exactly what this product refuses to produce.
        """
        conversation = await self._require(conversation_id, workspace_id)
        rows = await self._messages.list_for_conversation(conversation_id, workspace_id)

        lines = [f"# {conversation.title}", ""]
        for message in rows:
            who = "You" if message.role is MessageRole.USER else "Avocado"
            when = message.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"## {who} · {when}")
            lines.append("")
            lines.append(message.content)
            if message.citations:
                lines.append("")
                lines.append("**Sources**")
                for index, citation in enumerate(message.citations, start=1):
                    name = citation.get("filename") or citation.get("document_id") or "source"
                    lines.append(f"{index}. {name}")
            lines.append("")

        slug = re.sub(r"[^a-z0-9]+", "-", conversation.title.lower()).strip("-") or "conversation"
        return f"{slug}.md", "\n".join(lines)

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
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> list[MessageResponse]:
        await self._require(conversation_id, workspace_id)
        rows = await self._messages.list_for_conversation(conversation_id, workspace_id)
        responses = [MessageResponse.model_validate(m) for m in rows]

        # One query for the whole thread rather than one per message.
        if self._feedback is not None and user_id is not None:
            ratings = await self._feedback.ratings_for(conversation_id, user_id)
            for response in responses:
                response.feedback = ratings.get(response.id)
        return responses

    async def rate(
        self,
        *,
        message_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        rating: FeedbackRating | None,
    ) -> None:
        """Record what a reader thought of one answer.

        The only honest signal this product gets about answer quality:
        retrieval metrics can say the right chunks came back, not whether the
        answer built from them was any use.
        """
        if self._feedback is None:
            raise NotFoundError("Message not found.")
        if not await self._feedback.belongs_to_workspace(message_id, workspace_id):
            raise NotFoundError("Message not found.")
        await self._feedback.set_rating(message_id=message_id, user_id=user_id, rating=rating)
        await self._feedback.commit()
        log.info("message_rated", message=str(message_id), rating=rating.value if rating else None)

    async def send(
        self,
        *,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        preferred_model: str | None,
        require_grounding: bool,
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

        preset = await self._resolve_preset(payload.preset_slug, user_id=user_id, org_id=org_id)

        try:
            (
                answer,
                citations,
                model_used,
                in_tokens,
                out_tokens,
                latency_ms,
                grounded,
            ) = await self._rag.answer(
                workspace_id=workspace_id,
                question=payload.content,
                history=history,
                preferred_model=preferred_model,
                require_grounding=require_grounding,
                document_ids=payload.document_ids or None,
                web_search=await self._web_search_enabled(conversation_id),
                tools=ToolRunner(self._servers) if self._servers else None,
                tool_slugs=await self._mcp_servers_enabled(conversation_id),
                preset_prompt=preset.system_prompt if preset else None,
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
                grounded=grounded,
                model_used=model_used,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                latency_ms=latency_ms,
                preset_id=preset.id if preset else None,
                preset_version=preset.version if preset else None,
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

    async def _web_search_enabled(self, conversation_id: uuid.UUID) -> bool:
        """Whether this conversation has web search switched on.

        Defaults follow the catalogue when nothing has been chosen, the same
        rule the tool picker shows, so the answer path and the switch a user
        looked at never disagree.
        """
        if self._tools is None:
            return False
        choices = await self._tools.choices(conversation_id)
        if choices:
            return choices.get(WEB_SEARCH_SLUG, False)
        return BY_SLUG[WEB_SEARCH_SLUG].enabled_by_default

    async def _resolve_preset(
        self, slug: str | None, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Preset | None:
        """Turn a slash command into the preset row, or nothing.

        A slug that resolves to nothing is not an error. The user typed
        something into a composer; failing the whole turn over a typo would be
        worse than answering without it, and the recorded `preset_id` says
        plainly whether one was applied.
        """
        if not slug or self._presets is None:
            return None
        preset = await self._presets.resolve_slug(slug, user_id=user_id, org_id=org_id)
        if preset is None:
            log.info("preset_not_found", slug=slug)
        return preset

    async def _mcp_servers_enabled(self, conversation_id: uuid.UUID) -> list[str]:
        """Which connected servers this conversation has switched on.

        Follows the same default rule the picker shows, so the answer path and
        the switch a user looked at never disagree. Nothing is enabled by
        default here: an operator connecting a server should not silently start
        sending every conversation's questions to it.
        """
        if self._tools is None or self._servers is None:
            return []
        catalogue = catalogue_for(self._servers.configs)
        remote = {tool.slug for tool in catalogue if tool.kind is ToolKind.MCP}
        if not remote:
            return []
        choices = await self._tools.choices(conversation_id)
        return sorted(slug for slug in remote if choices.get(slug, False))

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
        require_grounding: bool,
        payload: MessageCreate,
    ) -> AsyncIterator[dict]:
        """Run a turn, choosing full-data analysis or grounded retrieval.

        Analytical spreadsheet turns emit `analysis_started`,
        `analysis_completed`, then `done`. Retrieval turns emit `citations`,
        one or more `token` events, then `done`.
        """
        await self._require(conversation_id, workspace_id)
        history = await self._messages.recent_history(
            conversation_id, workspace_id, limit=HISTORY_WINDOW
        )
        # The streamed turn is the one the UI actually uses, so a preset that
        # only worked on the plain POST would look built and do nothing.
        preset = await self._resolve_preset(payload.preset_slug, user_id=user_id, org_id=org_id)

        await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.USER,
                content=payload.content,
            )
        )
        await self._messages.commit()

        if await self._wants_report(workspace_id, payload):
            yield {"event": "report_started", "data": {}}
            try:
                report = await self._report.generate(
                    workspace_id=workspace_id,
                    org_id=org_id,
                    user_id=user_id,
                    focus=payload.content,
                    preferred_model=preferred_model,
                )
            except AvocadoError as exc:
                await self._record_failure(conversation_id, workspace_id, exc.detail)
                yield {"event": "error", "data": {"detail": exc.detail}}
                return

            artifact = report.model_dump(mode="json")
            await self._finish_stream(
                conversation_id,
                workspace_id,
                org_id,
                user_id,
                report.thesis,
                [],
                report.model_used,
                0,
                0,
                0,
                grounded=True,
                record_usage=False,
                report_artifact=artifact,
            )
            yield {"event": "report_completed", "data": {"report": artifact}}
            yield {
                "event": "done",
                "data": {
                    "model": report.model_used or "",
                    "citations": [],
                    "grounded": True,
                },
            }
            return

        analysis_document = await self._analysis_document(
            workspace_id=workspace_id,
            question=payload.content,
            document_ids=payload.document_ids,
        )
        if analysis_document is not None:
            yield {
                "event": "analysis_started",
                "data": {
                    "document_id": str(analysis_document.id),
                    "document_name": analysis_document.filename,
                },
            }
            try:
                run = await self._analysis.run(
                    workspace_id=workspace_id,
                    org_id=org_id,
                    document_id=analysis_document.id,
                    user_id=user_id,
                    question=payload.content,
                    table_id=None,
                    preferred_model=preferred_model,
                )
            except AvocadoError as exc:
                await self._record_failure(conversation_id, workspace_id, exc.detail)
                yield {"event": "error", "data": {"detail": exc.detail}}
                return

            answer = run.result_summary or "The full-data analysis is ready."
            await self._finish_stream(
                conversation_id,
                workspace_id,
                org_id,
                user_id,
                answer,
                [],
                run.model_used,
                0,
                0,
                run.execution_ms or 0,
                grounded=True,
                record_usage=False,
            )
            yield {
                "event": "analysis_completed",
                "data": {
                    "document_id": str(analysis_document.id),
                    "document_name": analysis_document.filename,
                    "run": run.model_dump(mode="json"),
                },
            }
            yield {
                "event": "done",
                "data": {
                    "model": run.model_used or "",
                    "citations": [],
                    "grounded": True,
                },
            }
            return

        hits = await self._rag.retrieve(
            workspace_id=workspace_id,
            question=payload.content,
            document_ids=payload.document_ids or None,
        )

        if not hits:
            text, citations, model_used, in_tokens, out_tokens, latency_ms, grounded = (
                await self._rag.answer(
                    workspace_id=workspace_id,
                    question=payload.content,
                    history=history,
                    preferred_model=preferred_model,
                    require_grounding=require_grounding,
                    document_ids=payload.document_ids or None,
                    web_search=await self._web_search_enabled(conversation_id),
                    tools=ToolRunner(self._servers) if self._servers else None,
                    tool_slugs=await self._mcp_servers_enabled(conversation_id),
                    preset_prompt=preset.system_prompt if preset else None,
                )
            )
            yield {"event": "token", "data": {"text": text}}
            await self._finish_stream(
                conversation_id,
                workspace_id,
                org_id,
                user_id,
                text,
                citations,
                model_used,
                in_tokens,
                out_tokens,
                latency_ms,
                grounded=grounded,
                preset=preset,
            )
            yield {
                "event": "done",
                "data": {
                    "model": model_used or "",
                    "citations": [],
                    "grounded": grounded,
                },
            }
            return

        provider, spec = self._router.resolve(
            task=TaskType.SYNTHESIS, preferred_model=preferred_model
        )

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
            system=with_preset(SYSTEM_PROMPT, preset.system_prompt if preset else None),
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
            grounded=True,
            preset=preset,
        )
        yield {
            "event": "done",
            "data": {
                "model": model_used,
                "citations": [c.model_dump(mode="json") for c in citations],
                "grounded": True,
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
        *,
        grounded: bool | None = None,
        record_usage: bool = True,
        report_artifact: dict | None = None,
        preset: Preset | None = None,
    ) -> None:
        await self._messages.add(
            Message(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                citations=[c.model_dump(mode="json") for c in citations],
                grounded=grounded,
                report_artifact=report_artifact,
                model_used=model_used,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                latency_ms=latency_ms,
                preset_id=preset.id if preset else None,
                preset_version=preset.version if preset else None,
            )
        )
        await self._messages.commit()
        if record_usage:
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

    async def _wants_report(self, workspace_id: uuid.UUID, payload: MessageCreate) -> bool:
        """Whether this turn should produce a whole-workspace executive report.

        A report reads across the whole workspace, so a turn scoped to a single
        document is left to single-file analysis instead. Strong report phrasing
        routes to a report whenever any spreadsheet exists; weak phrasing like
        "dashboard" only does so when there are several datasets to synthesise.
        """
        if len(payload.document_ids) == 1:
            return False
        strong = bool(STRONG_REPORT_INTENT.search(payload.content))
        weak = bool(WEAK_REPORT_INTENT.search(payload.content))
        if not (strong or weak):
            return False
        ready = await self._documents.list_ready(workspace_id)
        analyzable = sum(1 for doc in ready if doc.doc_type in ANALYZABLE_TYPES)
        if analyzable == 0:
            return False
        return strong or analyzable >= 2

    async def _analysis_document(
        self,
        *,
        workspace_id: uuid.UUID,
        question: str,
        document_ids: list[uuid.UUID],
    ) -> Document | None:
        """Select an explicitly relevant spreadsheet for analytical requests.

        Ambiguous requests still use RAG instead of silently analysing the
        wrong file. A filename/subject match or a single scoped spreadsheet is
        enough to route the turn through the full-data sandbox.
        """
        if not ANALYSIS_INTENT.search(question):
            return None

        candidates = [
            document
            for document in await self._documents.list_ready(workspace_id)
            if document.doc_type in ANALYZABLE_TYPES
            and (not document_ids or document.id in document_ids)
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        question_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
        ranked: list[tuple[int, Document]] = []
        for document in candidates:
            filename_tokens = set(re.findall(r"[a-z0-9]+", document.filename.lower()))
            # Generic file words do not prove that this is the intended table.
            filename_tokens -= {"csv", "xlsx", "data", "table", "report"}
            ranked.append((len(question_tokens & filename_tokens), document))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1] if ranked[0][0] > 0 else None

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
