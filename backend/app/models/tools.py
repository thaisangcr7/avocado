"""Which tools a conversation has switched on.

There is deliberately no `tools` table. The catalogue lives in code
(`services/tool_catalogue.py`), so a fresh deployment has a populated registry
with no seed data to keep in step — and a table that would only ever mirror a
constant is a synchronisation problem, not a feature.

That makes the slug the identifier. When organisation-defined MCP servers
arrive they get their own table, and this column keeps working: a slug resolves
against the built-in catalogue first, then against whatever the organisation
registered.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConversationTool(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One explicit tool choice for one conversation.

    Rows record *decisions*, not just the enabled set, which is why `enabled`
    exists rather than presence meaning on. Without it, deliberately switching
    everything off is indistinguishable from never having chosen, and the
    defaults come back the next time the conversation is opened.
    """

    __tablename__ = "conversation_tools"
    __table_args__ = (
        UniqueConstraint("conversation_id", "tool_slug", name="uq_conversation_tools_pair"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tool_slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
