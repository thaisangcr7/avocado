"""Rewriting a half-typed question before it is sent.

Small on purpose. The wand runs while someone is waiting with their hand still
on the keyboard, so it uses the cheap tier — a slow rewrite is one nobody
presses a second time.

What it must not do is answer. The failure mode of a "make this better" prompt
is a model that helpfully replies to the question instead of sharpening it, and
the user then sends an answer as their question.
"""

from __future__ import annotations

from app.clients.llm.base import ChatMessage
from app.clients.llm.router import ModelRouter, TaskType
from app.core.errors import ProviderError, ValidationError
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_DRAFT_CHARS = 2000

ENHANCE_PROMPT = """You rewrite a half-typed question so an assistant can answer it well.

The assistant answers only from a team's own uploaded documents.

Rules:
- Return only the rewritten question. No preamble, no explanation, no quotes.
- Never answer it. You are sharpening the question, not responding to it.
- Keep the user's intent and subject exactly. Do not add requirements they did \
not ask for, and do not invent specifics they did not mention.
- Prefer one clear sentence. Make vague references concrete only where the \
draft already implies them.
- If the draft is already clear, return it unchanged."""


class EnhanceService:
    def __init__(self, *, router: ModelRouter) -> None:
        self._router = router

    async def enhance(self, draft: str) -> str:
        """Return a sharpened draft, or the original if that cannot be done.

        Falls back to the draft rather than failing the request. The wand is a
        convenience beside a composer that already works; taking the composer
        down with it would be a poor trade.
        """
        text = draft.strip()
        if not text:
            raise ValidationError("There is nothing to rewrite.")
        if len(text) > MAX_DRAFT_CHARS:
            raise ValidationError("That draft is too long to rewrite.")

        try:
            provider, spec = self._router.resolve(task=TaskType.ENHANCE, preferred_model=None)
            result = await provider.generate(
                messages=[ChatMessage(role="user", content=text)],
                model=spec.id,
                system=ENHANCE_PROMPT,
                # A rewrite is about as long as its input. Capping it stops a
                # model that decided to answer from returning an essay.
                max_tokens=300,
            )
        except (ProviderError, ValidationError):
            log.info("enhance_unavailable")
            return text

        rewritten = result.text.strip().strip('"')
        # A model that ignored the instruction and answered instead would
        # return something far longer than the question. Better the original
        # draft than silently replacing someone's question with an answer.
        if not rewritten or len(rewritten) > max(len(text) * 4, 400):
            log.info("enhance_rejected", original=len(text), rewritten=len(rewritten))
            return text
        return rewritten
