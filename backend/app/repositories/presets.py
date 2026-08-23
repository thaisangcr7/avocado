"""Data access for presets, pins and shares.

Org-scoped rather than workspace-scoped, so `WorkspaceScopedRepository` does
not apply. `org_id` is a required argument on every read and write here for the
same reason it is there: a caller cannot fetch by id alone, so a client-supplied
identifier is never trusted on its own.

The visibility rule lives in `_visible_to` and nowhere else. Spreading it across
call sites is how one query eventually forgets a clause and shows somebody a
private prompt.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import Select, delete, func, or_, select

from app.models.enums import PresetScope
from app.models.presets import Preset, PresetPin, PresetShare
from app.repositories.base import BaseRepository

# The tabs the picker offers. `all` is everything visible; the rest narrow it.
PresetFilter = Literal["all", "pinned", "mine", "native", "community", "shared"]


class PresetRepository(BaseRepository[Preset]):
    model = Preset

    @staticmethod
    def _visible_to(user_id: uuid.UUID, org_id: uuid.UUID):
        """The one definition of what a person may see.

        Their organisation's shared prompts, their own, and anything shared
        with them by name. A private preset belonging to someone else is not
        here, which is the whole point.
        """
        return (
            Preset.org_id == org_id,
            or_(
                Preset.scope.in_((PresetScope.ORG, PresetScope.PUBLISHED)),
                Preset.created_by_user_id == user_id,
                Preset.id.in_(select(PresetShare.preset_id).where(PresetShare.user_id == user_id)),
            ),
        )

    def _select_visible(self, user_id: uuid.UUID, org_id: uuid.UUID) -> Select:
        return select(Preset).where(*self._visible_to(user_id, org_id))

    async def get_visible(
        self, preset_id: uuid.UUID, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Preset | None:
        """One preset, if this person is allowed to see it at all."""
        stmt = self._select_visible(user_id, org_id).where(Preset.id == preset_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str, user_id: uuid.UUID, org_id: uuid.UUID) -> Preset | None:
        """Resolve a slash command to a preset this person may use."""
        stmt = self._select_visible(user_id, org_id).where(Preset.slug == slug)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def slug_taken(
        self, slug: str, org_id: uuid.UUID, *, excluding: uuid.UUID | None = None
    ) -> bool:
        """Slugs are unique per organisation, visible or not.

        Deliberately not filtered by visibility: a slug held by someone else's
        private preset is still taken, and reporting it free would fail on the
        insert instead.
        """
        stmt = select(Preset.id).where(Preset.org_id == org_id, Preset.slug == slug)
        if excluding is not None:
            stmt = stmt.where(Preset.id != excluding)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def list_visible(
        self,
        *,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        which: PresetFilter = "all",
        search: str | None = None,
        limit: int = 100,
    ) -> list[Preset]:
        stmt = self._select_visible(user_id, org_id)

        if which == "pinned":
            stmt = stmt.where(
                Preset.id.in_(select(PresetPin.preset_id).where(PresetPin.user_id == user_id))
            )
        elif which == "mine":
            stmt = stmt.where(Preset.created_by_user_id == user_id)
        elif which == "native":
            stmt = stmt.where(Preset.is_native.is_(True))
        elif which == "community":
            # Published by a person, as opposed to shipped with the product.
            stmt = stmt.where(Preset.scope == PresetScope.PUBLISHED, Preset.is_native.is_(False))
        elif which == "shared":
            stmt = stmt.where(
                Preset.id.in_(select(PresetShare.preset_id).where(PresetShare.user_id == user_id))
            )

        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Preset.name).like(like),
                    func.lower(Preset.slug).like(like),
                    func.lower(Preset.description).like(like),
                )
            )

        stmt = stmt.order_by(Preset.is_native.desc(), Preset.name.asc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())


class PresetPinRepository(BaseRepository[PresetPin]):
    model = PresetPin

    async def pinned_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        stmt = select(PresetPin.preset_id).where(PresetPin.user_id == user_id)
        return set((await self._session.execute(stmt)).scalars().all())

    async def set_pinned(self, *, user_id: uuid.UUID, preset_id: uuid.UUID, pinned: bool) -> None:
        if not pinned:
            await self._session.execute(
                delete(PresetPin).where(
                    PresetPin.user_id == user_id, PresetPin.preset_id == preset_id
                )
            )
            await self._session.flush()
            return

        existing = await self._session.execute(
            select(PresetPin.id).where(
                PresetPin.user_id == user_id, PresetPin.preset_id == preset_id
            )
        )
        if existing.scalar_one_or_none() is None:
            self._session.add(PresetPin(user_id=user_id, preset_id=preset_id))
            await self._session.flush()


class PresetShareRepository(BaseRepository[PresetShare]):
    model = PresetShare

    async def share(
        self, *, preset_id: uuid.UUID, user_id: uuid.UUID, shared_by_user_id: uuid.UUID
    ) -> None:
        """Idempotent: sharing twice is not an error, it is the same grant."""
        existing = await self._session.execute(
            select(PresetShare.id).where(
                PresetShare.preset_id == preset_id, PresetShare.user_id == user_id
            )
        )
        if existing.scalar_one_or_none() is None:
            self._session.add(
                PresetShare(
                    preset_id=preset_id,
                    user_id=user_id,
                    shared_by_user_id=shared_by_user_id,
                )
            )
            await self._session.flush()

    async def recipients(self, preset_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(PresetShare.user_id).where(PresetShare.preset_id == preset_id)
        return list((await self._session.execute(stmt)).scalars().all())
