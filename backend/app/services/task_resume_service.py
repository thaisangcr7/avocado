"""Picking a task back up.

Architecture §11: returning to a task after two days on something else should
start with "here is where we left off", not a blank chat. So a task carries its
own conversation, and resuming it synthesises where things stood rather than
merely reopening the thread.

The summary is written by a cheap model over the thread's own messages. When no
model is configured — or the call fails — it falls back to a deterministic
rendering and says so via `synthesized: false`. A resume that quietly returns
boilerplate dressed as synthesis would be worse than one that admits what it
is.
"""

from __future__ import annotations

import uuid

from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.conversations import Conversation
from app.models.enums import MessageRole, TaskStatus
from app.repositories.conversations import ConversationRepository, MessageRepository
from app.repositories.projects import ProjectRepository, TaskRepository
from app.schemas.projects import TaskResponse, TaskResumeResponse
from app.services.project_service import ProjectService
from app.services.rag_service import ANSWER_VOICE

log = get_logger(__name__)

# Enough of the thread to summarise without resending an entire history.
RESUME_WINDOW = 20

RESUME_PROMPT = """Summarise where this piece of work stands, for someone \
returning to it after a few days.

Cover, in at most four sentences:
- what was being worked out
- what was decided or established
- what the immediate next step appears to be

Write plain prose addressed to the person returning. Do not greet them, do not \
restate the task title, and do not invent anything the messages do not say. If \
the thread is too thin to summarise, say so in one sentence.""" + ANSWER_VOICE


class TaskResumeService:
    def __init__(
        self,
        *,
        tasks: TaskRepository,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        messages: MessageRepository,
        router: ModelRouter,
        project_service: ProjectService,
    ) -> None:
        self._tasks = tasks
        self._projects = projects
        self._conversations = conversations
        self._messages = messages
        self._router = router
        self._projects_service = project_service

    async def resume(
        self,
        *,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        team_id: uuid.UUID,
        user_id: uuid.UUID,
        preferred_model: str | None,
    ) -> TaskResumeResponse:
        task = await self._tasks.get_visible(
            task_id,
            workspace_id,
            user_id,
            is_admin=await self._projects_service.is_workspace_admin(user_id, team_id),
        )
        if task is None:
            raise NotFoundError("Task not found.")

        conversation = await self._conversations.get_for_task(task_id, workspace_id)
        if conversation is None:
            # Created on demand, so a task that has never been discussed still
            # resumes into somewhere to talk.
            conversation = await self._conversations.add(
                Conversation(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    task_id=task_id,
                    title=task.title[:300],
                )
            )
            await self._conversations.commit()

        history = await self._messages.recent_history(
            conversation.id, workspace_id, limit=RESUME_WINDOW
        )
        summary, synthesized, _ = await self._summarise(task, history, preferred_model)

        return TaskResumeResponse(
            task=TaskResponse.model_validate(task),
            conversation_id=conversation.id,
            summary=summary,
            message_count=len(history),
            last_activity_at=history[-1].created_at if history else None,
            synthesized=synthesized,
        )

    async def _summarise(
        self, task, history: list, preferred_model: str | None
    ) -> tuple[str, bool, str | None]:
        """Returns (summary, was_synthesized, model_used)."""
        if not history:
            return (_opening_line(task), False, None)

        transcript = "\n\n".join(
            f"{'You' if m.role is MessageRole.USER else 'Avocado'}: {m.content[:1500]}"
            for m in history
        )
        context = (
            f"Task: {task.title}\n"
            f"Status: {task.status.value}\n"
            + (f"Notes: {task.notes[:1000]}\n" if task.notes else "")
            + f"\nThread:\n{transcript}"
        )

        try:
            provider, spec = self._router.resolve(
                task=TaskType.SUMMARIZATION, preferred_model=preferred_model
            )
            result = await provider.generate(
                messages=[ChatMessage(role="user", content=context)],
                model=spec.id,
                system=RESUME_PROMPT,
                max_tokens=512,
            )
            if result.text.strip():
                return (result.text.strip(), True, result.model)
        except Exception:
            # A resume that fails must still open the task. Losing the thread
            # because the summary could not be written would be the worse
            # outcome by far.
            log.info("task_resume_summary_unavailable", task_id=str(task.id))

        return (_deterministic_summary(task, history), False, None)


def _opening_line(task) -> str:
    """What to say about a task nobody has discussed yet."""
    parts = [f"Nothing has been discussed for “{task.title}” yet."]
    if task.due_date:
        parts.append(f"It is due {task.due_date.isoformat()}.")
    if task.status is TaskStatus.BLOCKED:
        parts.append("It is currently marked blocked.")
    return " ".join(parts)


def _deterministic_summary(task, history: list) -> str:
    """A factual fallback when no model wrote the summary.

    States what is verifiably true — how much was said, when, and what the last
    exchange was about — rather than imitating synthesis.
    """
    last = history[-1]
    who = "you" if last.role is MessageRole.USER else "Avocado"
    when = last.created_at.date().isoformat()
    excerpt = last.content.strip().replace("\n", " ")[:200]

    lines = [
        f"{len(history)} message{'s' if len(history) != 1 else ''} on this task; "
        f"last activity {when}, from {who}:",
        f"“{excerpt}{'…' if len(last.content) > 200 else ''}”",
    ]
    if task.status is TaskStatus.BLOCKED:
        lines.append("This task is marked blocked.")
    if task.due_date:
        lines.append(f"Due {task.due_date.isoformat()}.")
    return "\n".join(lines)
