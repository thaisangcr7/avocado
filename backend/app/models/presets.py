"""Presets — named, shareable system prompts.

A preset is the instruction a conversation starts under, saved so it can be
named, reused and handed to a colleague. `/sage` is a preset; so is the house
style for writing a Dockerfile.

Three tables rather than one, because two of the relationships are many-to-many
and belong to the *reader*, not the preset: pinning is one person's shortcut,
and a share is a grant to one person. Folding either into the preset row would
make one user's shortcut a property of everyone's copy.

Scoped by organisation, not workspace. A preset is how a team writes, which
does not change between one workspace and the next, and duplicating it per
workspace would mean editing it in five places. That makes `org_id` the tenant
boundary here, and the repository requires it on every read — the same
guarantee `WorkspaceScopedRepository` gives, enforced the way `invitations`
already does it for org-level data.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PresetScope


class Preset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "presets"
    __table_args__ = (
        # The slash command. Unique per organisation because that is the
        # namespace a user types into — two `/sage` in one org would make the
        # composer ambiguous.
        UniqueConstraint("org_id", "slug", name="uq_presets_org_slug"),
        Index("ix_presets_org_scope", "org_id", "scope"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Nullable so a preset survives the person who wrote it leaving. The
    # organisation's shared prompts should not disappear with an offboarding.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    # The whole point of the row. Prepended server-side; never accepted from a
    # client, which would make the system prompt a user-controlled field.
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # A suggestion, not a pin. The router still decides, so a preset written
    # against a model that is later retired keeps working.
    model_hint: Mapped[str | None] = mapped_column(String(120))

    scope: Mapped[PresetScope] = mapped_column(
        Enum(PresetScope, name="preset_scope", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PresetScope.PRIVATE,
    )
    # Platform-authored. Only an org admin may set it, so "native" keeps
    # meaning "vetted" rather than "whoever ticked the box".
    is_native: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Bumped on every edit. A conversation records which version it ran under,
    # so changing a preset cannot silently rewrite what a past answer was told.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PresetPin(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One person's shortcut to one preset."""

    __tablename__ = "preset_pins"
    __table_args__ = (UniqueConstraint("user_id", "preset_id", name="uq_preset_pins_pair"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    preset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("presets.id", ondelete="CASCADE"), index=True
    )


class PresetShare(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A grant of one private preset to one person.

    Only meaningful for `PRIVATE` scope: anything wider is already visible to
    the whole organisation, and a share row would add nothing.
    """

    __tablename__ = "preset_shares"
    __table_args__ = (UniqueConstraint("preset_id", "user_id", name="uq_preset_shares_pair"),)

    preset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("presets.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    shared_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
