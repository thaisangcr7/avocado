"""Repository base classes.

Two rules this layer exists to make structural rather than remembered:

1. Nothing above this layer imports SQLAlchemy. Services take repositories.
2. Every query against a tenant-scoped table filters on `workspace_id`.

`WorkspaceScopedRepository` enforces (2) by construction: `workspace_id` is a
required argument on every read and write, and the base applies it as a
predicate. A caller cannot fetch by id alone — there is no method that accepts
only an id — so a client-supplied identifier can never be trusted on its own.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Cursor, Page, PageParams
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Data access for a model with no tenant scope (organizations, users)."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self._session.get(self.model, entity_id)

    async def delete(self, entity: ModelT) -> None:
        await self._session.delete(entity)
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, entity: ModelT) -> ModelT:
        """Reload server-computed columns after an UPDATE.

        `updated_at` is set by the database (`onupdate=func.now()`), so
        SQLAlchemy expires it once the UPDATE is flushed — it cannot know the
        new value. Reading it afterwards would trigger lazy IO, which raises
        `MissingGreenlet` under asyncio. Any update path that then serialises
        the entity has to refresh it first.
        """
        await self._session.refresh(entity)
        return entity


class WorkspaceScopedRepository(BaseRepository[ModelT]):
    """Data access for a model carrying `workspace_id`.

    Tenant isolation is applied here and nowhere else, so it cannot be
    forgotten at a call site.
    """

    async def get_scoped(self, entity_id: uuid.UUID, workspace_id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.id == entity_id,
            self.model.workspace_id == workspace_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # Deliberately shadows `BaseRepository.get` to remove the unscoped path
    # from this subclass entirely.
    async def get(self, entity_id: uuid.UUID) -> ModelT | None:  # type: ignore[override]
        raise NotImplementedError(
            f"{type(self).__name__} is workspace-scoped: use get_scoped(id, workspace_id)."
        )

    def _scoped_select(self, workspace_id: uuid.UUID) -> Select[tuple[ModelT]]:
        return select(self.model).where(self.model.workspace_id == workspace_id)

    async def count(self, workspace_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.workspace_id == workspace_id)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def delete_scoped(self, entity_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
        stmt = delete(self.model).where(
            self.model.id == entity_id,
            self.model.workspace_id == workspace_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0

    async def paginate(
        self,
        workspace_id: uuid.UUID,
        params: PageParams,
        *,
        extra_filters: list[Any] | None = None,
    ) -> Page[ModelT]:
        """Keyset pagination, newest first.

        Ordered by `(created_at DESC, id DESC)` — the id breaks ties so rows
        created in the same transaction have a stable, total order and cannot
        be skipped or repeated across pages.
        """
        stmt = self._scoped_select(workspace_id)
        for condition in extra_filters or []:
            stmt = stmt.where(condition)

        cursor = params.decoded_cursor()
        if cursor:
            stmt = stmt.where(
                (self.model.created_at, self.model.id) < (cursor.created_at, cursor.item_id)
            )

        stmt = stmt.order_by(self.model.created_at.desc(), self.model.id.desc())
        # Fetch one extra to learn whether another page exists without a
        # second COUNT query.
        stmt = stmt.limit(params.limit + 1)

        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > params.limit
        items = rows[: params.limit]

        next_cursor = (
            Cursor(created_at=items[-1].created_at, item_id=items[-1].id).encode()
            if has_more and items
            else None
        )
        return Page(items=items, next_cursor=next_cursor, has_more=has_more)
