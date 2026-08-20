"""Proactive suggestions — a digest, not a record.

Architecture §5 is explicit that suggestions are not a persisted table: they
are generated on demand or on a schedule and cached, because they describe a
moment rather than a fact worth keeping.

The division of labour matters. The *facts* are computed deterministically —
which tasks are overdue, which documents are new since the last visit, which
threads were left mid-question. Those are exact, cheap, and a model would only
add a chance of being wrong about them. The model's job is narrower: to phrase
and order the nudges well. When no model is configured, deterministic wording
is used and the response says `model_used: null`, the same honesty as a chat
message.

"Since your last visit" is itself ephemeral state, so it lives in Redis
alongside the cache rather than in a column. Absent it, the window falls back
to a recent period, which is the right behaviour for a first visit anyway.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.core.logging import get_logger
from app.models.enums import SuggestionKind
from app.repositories.conversations import ConversationRepository
from app.repositories.documents import DocumentRepository
from app.repositories.projects import TaskRepository
from app.schemas.projects import Suggestion, SuggestionsResponse

log = get_logger(__name__)

# How long a digest stays fresh. Long enough that opening three tabs does not
# recompute it three times; short enough that finishing a task makes its nudge
# disappear promptly.
CACHE_TTL_SECONDS = 300

# First-visit window, and the horizon for "due soon".
DEFAULT_LOOKBACK_DAYS = 7
DUE_SOON_DAYS = 3

MAX_SUGGESTIONS = 6

# Higher sorts first. Overdue work outranks everything; a new document is worth
# mentioning but should never bury a deadline.
_PRIORITY: dict[SuggestionKind, int] = {
    SuggestionKind.TASK_OVERDUE: 100,
    SuggestionKind.TASK_DUE: 80,
    SuggestionKind.TASK_BLOCKED: 60,
    SuggestionKind.FAILED_DOCUMENT: 50,
    SuggestionKind.UNFINISHED_THREAD: 40,
    SuggestionKind.NEW_DOCUMENT: 20,
}

PHRASING_PROMPT = """Rewrite each nudge as one short, plain sentence a \
colleague would say.

Rules:
- Keep the same order and the same count. Return exactly one line per nudge.
- Preserve every fact: names, dates, counts. Do not add any.
- No greetings, no exclamation marks, no "don't forget".
- Under 90 characters per line.

Return only the lines, one per nudge, in order."""


class SuggestionService:
    def __init__(
        self,
        *,
        tasks: TaskRepository,
        documents: DocumentRepository,
        conversations: ConversationRepository,
        router: ModelRouter,
        redis=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self._tasks = tasks
        self._documents = documents
        self._conversations = conversations
        self._router = router
        self._redis = redis

    # --- cache and last-visit state ----------------------------------------

    def _cache_key(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> str:
        return f"suggestions:{workspace_id}:{user_id}"

    def _seen_key(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> str:
        return f"lastseen:{workspace_id}:{user_id}"

    async def _cached(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> SuggestionsResponse | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(self._cache_key(workspace_id, user_id))
        except Exception:
            # A cache that is down must not take suggestions with it.
            log.debug("suggestion_cache_unavailable", exc_info=True)
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return SuggestionsResponse(**{**payload, "cached": True})
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    async def _store(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, response: SuggestionsResponse
    ) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.setex(
                self._cache_key(workspace_id, user_id),
                CACHE_TTL_SECONDS,
                response.model_dump_json(),
            )
        except Exception:
            log.debug("suggestion_cache_write_failed", exc_info=True)

    async def _last_seen(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> datetime:
        fallback = datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        if self._redis is None:
            return fallback
        try:
            raw = await self._redis.get(self._seen_key(workspace_id, user_id))
        except Exception:
            return fallback
        if not raw:
            return fallback
        try:
            seen = datetime.fromisoformat(raw)
            return seen if seen.tzinfo else seen.replace(tzinfo=UTC)
        except ValueError:
            return fallback

    async def mark_seen(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Record that the user has now looked.

        Called after a digest is delivered, so the next one covers what changed
        *since* rather than repeating the same nudges forever.
        """
        if self._redis is None:
            return
        try:
            await self._redis.setex(
                self._seen_key(workspace_id, user_id),
                60 * 60 * 24 * 30,
                datetime.now(UTC).isoformat(),
            )
        except Exception:
            log.debug("last_seen_write_failed", exc_info=True)

    # --- the digest --------------------------------------------------------

    async def suggestions(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        preferred_model: str | None,
        refresh: bool = False,
    ) -> SuggestionsResponse:
        if not refresh:
            cached = await self._cached(workspace_id, user_id)
            if cached is not None:
                return cached

        facts = await self._gather(workspace_id, user_id)
        facts.sort(key=lambda s: (-s.priority, s.title))
        facts = facts[:MAX_SUGGESTIONS]

        model_used = None
        if facts:
            model_used = await self._phrase(facts, preferred_model)

        response = SuggestionsResponse(
            items=facts,
            generated_at=datetime.now(UTC),
            cached=False,
            model_used=model_used,
        )
        await self._store(workspace_id, user_id, response)
        await self.mark_seen(workspace_id, user_id)

        log.info(
            "suggestions_generated",
            workspace_id=str(workspace_id),
            count=len(facts),
            phrased_by=model_used or "deterministic",
        )
        return response

    async def _gather(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Suggestion]:
        """Every candidate nudge, computed exactly.

        No model is involved here on purpose: whether a task is overdue is a
        fact, and asking a model to determine it only introduces a chance of
        being wrong about something the database already knows.
        """
        today = date.today()
        since = await self._last_seen(workspace_id, user_id)
        out: list[Suggestion] = []

        # Tasks assigned to this user, due within the horizon or already past.
        due = await self._tasks.due_for_user(
            workspace_id, user_id, through=today + timedelta(days=DUE_SOON_DAYS)
        )
        for task in due:
            overdue = task.due_date is not None and task.due_date < today
            kind = SuggestionKind.TASK_OVERDUE if overdue else SuggestionKind.TASK_DUE
            when = (
                "overdue"
                if overdue
                else "due today"
                if task.due_date == today
                else f"due {task.due_date.isoformat()}"
            )
            out.append(
                _suggestion(
                    kind,
                    title=f"{task.title} is {when}",
                    detail=task.notes[:160] if task.notes else None,
                    task_id=task.id,
                    project_id=task.project_id,
                )
            )

        for task in await self._tasks.blocked_for_user(workspace_id, user_id):
            out.append(
                _suggestion(
                    SuggestionKind.TASK_BLOCKED,
                    title=f"{task.title} is blocked",
                    detail=task.notes[:160] if task.notes else None,
                    task_id=task.id,
                    project_id=task.project_id,
                )
            )

        # Documents that appeared since the last visit.
        ready = await self._documents.list_ready(workspace_id)
        new_documents = [d for d in ready if d.created_at > since]
        if len(new_documents) == 1:
            out.append(
                _suggestion(
                    SuggestionKind.NEW_DOCUMENT,
                    title=f"{new_documents[0].filename} was added",
                    document_id=new_documents[0].id,
                )
            )
        elif new_documents:
            out.append(
                _suggestion(
                    SuggestionKind.NEW_DOCUMENT,
                    title=f"{len(new_documents)} new documents were added",
                    detail=", ".join(d.filename for d in new_documents[:3]),
                )
            )

        # A document that failed to process is invisible to retrieval, so the
        # person who uploaded it needs to know rather than wonder why answers
        # are missing.
        failed = [
            d
            for d in await self._documents.list_recent_failed(workspace_id)
            if d.uploaded_by == user_id
        ]
        for document in failed[:2]:
            out.append(
                _suggestion(
                    SuggestionKind.FAILED_DOCUMENT,
                    title=f"{document.filename} could not be processed",
                    detail=document.error_message,
                    document_id=document.id,
                )
            )

        # Threads where the user asked the last question and never returned.
        for conversation in await self._conversations.unfinished_for_user(workspace_id, user_id):
            out.append(
                _suggestion(
                    SuggestionKind.UNFINISHED_THREAD,
                    title=f"You left “{conversation.title}” unfinished",
                    conversation_id=conversation.id,
                )
            )

        return out

    async def _phrase(
        self, suggestions: list[Suggestion], preferred_model: str | None
    ) -> str | None:
        """Rewrite the nudges in a human voice. Returns the model used, if any.

        Failure is not an error: the deterministic titles are already correct
        and readable, so a phrasing pass that does not happen costs nothing but
        polish.
        """
        try:
            provider, spec = self._router.resolve(
                task=TaskType.TITLE, preferred_model=preferred_model
            )
            numbered = "\n".join(f"{i + 1}. {s.title}" for i, s in enumerate(suggestions))
            result = await provider.generate(
                messages=[ChatMessage(role="user", content=numbered)],
                model=spec.id,
                system=PHRASING_PROMPT,
                max_tokens=400,
            )
            lines = [
                line.strip().lstrip("0123456789. ").strip()
                for line in result.text.strip().splitlines()
                if line.strip()
            ]
            # Only accept a rewrite that preserved the count. A model that
            # merged or dropped nudges would silently lose one, and a lost
            # deadline is worse than an unpolished sentence.
            if len(lines) == len(suggestions):
                for suggestion, line in zip(suggestions, lines, strict=True):
                    suggestion.title = line[:200]
                return result.model
            log.debug("suggestion_phrasing_count_mismatch")
        except Exception:
            log.debug("suggestion_phrasing_unavailable", exc_info=True)
        return None


def _suggestion(kind: SuggestionKind, *, title: str, **fields) -> Suggestion:
    """Build a nudge with a stable, content-derived id.

    The id has to survive regeneration so a client-side dismissal sticks —
    suggestions are not stored, so the server cannot remember it for them.
    """
    identity = json.dumps(
        {"kind": kind.value, **{k: str(v) for k, v in fields.items() if v}},
        sort_keys=True,
    )
    return Suggestion(
        id=hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind=kind,
        title=title,
        priority=_PRIORITY[kind],
        **fields,
    )
