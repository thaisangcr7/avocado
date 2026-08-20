"""Invitation data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.models.invitations import Invitation, InvitationStatus
from app.repositories.base import BaseRepository


class InvitationRepository(BaseRepository[Invitation]):
    model = Invitation

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        """Look an invitation up by the hash of its token.

        The raw token is never stored, so this is the only way to resolve one —
        which is the point: a database read cannot reconstruct a working link.
        """
        stmt = select(Invitation).where(Invitation.token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_pending(self, team_id: uuid.UUID, email: str) -> Invitation | None:
        stmt = select(Invitation).where(
            Invitation.team_id == team_id,
            func.lower(Invitation.email) == email.lower(),
            Invitation.status == InvitationStatus.PENDING,
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def list_for_team(
        self, team_id: uuid.UUID, *, pending_only: bool = True
    ) -> list[Invitation]:
        stmt = select(Invitation).where(Invitation.team_id == team_id)
        if pending_only:
            stmt = stmt.where(Invitation.status == InvitationStatus.PENDING)
        stmt = stmt.order_by(Invitation.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_for_org(self, invitation_id: uuid.UUID, org_id: uuid.UUID) -> Invitation | None:
        """Scoped fetch — an invitation id alone is a client-supplied value."""
        stmt = select(Invitation).where(Invitation.id == invitation_id, Invitation.org_id == org_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def expire_stale(self) -> int:
        """Mark elapsed invitations expired.

        Acceptance already refuses an elapsed invitation, so this is only for
        keeping listings honest — a pending row whose deadline has passed reads
        as still open otherwise.
        """
        stmt = (
            update(Invitation)
            .where(
                Invitation.status == InvitationStatus.PENDING,
                Invitation.expires_at < datetime.now(UTC),
            )
            .values(status=InvitationStatus.EXPIRED)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount
