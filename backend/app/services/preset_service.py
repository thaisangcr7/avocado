"""Presets: creating them, finding them, and who may do what.

The shape rules are on the schemas. What lives here is everything needing a
lookup — is this slug taken, may this person publish to the whole organisation,
is that user even in the same tenant.

Two rules are worth stating out loud because getting either wrong is a leak
rather than a bug:

- **The system prompt is never accepted from a client at send time.** A preset
  is applied by slug; the text is read from the row. A client that could post
  its own system prompt would not need presets at all.
- **A share is checked against the recipient's organisation**, not just their
  id. Sharing is the one operation that names another user, and an unchecked id
  is how a private prompt crosses a tenant.
"""

from __future__ import annotations

import uuid

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.logging import get_logger
from app.models.enums import PresetScope, Role
from app.models.presets import Preset
from app.repositories.presets import (
    PresetFilter,
    PresetPinRepository,
    PresetRepository,
    PresetShareRepository,
)
from app.repositories.tenancy import UserRepository
from app.schemas.presets import (
    PresetCreate,
    PresetListResponse,
    PresetResponse,
    PresetUpdate,
    slugify,
)
from app.services.membership_service import MembershipService

log = get_logger(__name__)

# How many times a derived slug is nudged before giving up. Two people naming a
# preset "Sage" is ordinary; two hundred is a caller doing something odd.
_SLUG_ATTEMPTS = 50


class PresetService:
    def __init__(
        self,
        *,
        presets: PresetRepository,
        pins: PresetPinRepository,
        shares: PresetShareRepository,
        users: UserRepository,
        access: MembershipService,
    ) -> None:
        self._presets = presets
        self._pins = pins
        self._shares = shares
        self._users = users
        self._access = access

    # --- reading -------------------------------------------------------

    async def _to_response(
        self, preset: Preset, *, user_id: uuid.UUID, pinned: set[uuid.UUID] | None = None
    ) -> PresetResponse:
        pinned_ids = pinned if pinned is not None else await self._pins.pinned_ids(user_id)
        response = PresetResponse.model_validate(preset)
        response.pinned = preset.id in pinned_ids
        response.is_mine = preset.created_by_user_id == user_id
        response.can_edit = await self._may_edit(preset, user_id)
        return response

    async def _may_edit(self, preset: Preset, user_id: uuid.UUID) -> bool:
        """Its author, or an org admin.

        A native preset is the platform's, so editing one is an admin act even
        for whoever originally wrote it.
        """
        if preset.is_native:
            return await self._access.is_org_admin(user_id)
        if preset.created_by_user_id == user_id:
            return True
        return await self._access.is_org_admin(user_id)

    async def list(
        self,
        *,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        which: PresetFilter = "all",
        search: str | None = None,
    ) -> PresetListResponse:
        found = await self._presets.list_visible(
            user_id=user_id, org_id=org_id, which=which, search=search
        )
        # Fetched once for the whole page rather than per row.
        pinned = await self._pins.pinned_ids(user_id)
        presets = [
            await self._to_response(preset, user_id=user_id, pinned=pinned) for preset in found
        ]
        return PresetListResponse(presets=presets, total=len(presets))

    async def get(
        self, preset_id: uuid.UUID, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> PresetResponse:
        preset = await self._require_visible(preset_id, user_id, org_id)
        return await self._to_response(preset, user_id=user_id)

    async def _require_visible(
        self, preset_id: uuid.UUID, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Preset:
        """Absent rather than forbidden, like every other scoped route.

        Someone else's private preset reads as 404: confirming the id exists is
        itself information they should not have.
        """
        preset = await self._presets.get_visible(preset_id, user_id, org_id)
        if preset is None:
            raise NotFoundError("Preset not found.")
        return preset

    # --- writing -------------------------------------------------------

    async def _resolve_slug(
        self,
        wanted: str | None,
        name: str,
        org_id: uuid.UUID,
        *,
        excluding: uuid.UUID | None = None,
    ) -> str:
        """Take the requested slug, or derive one and step around collisions.

        An explicitly requested slug that is taken is a conflict the caller
        should see. A *derived* one is not — they asked for a name, not a slug,
        so a second "Sage" quietly becomes `sage-2`.
        """
        if wanted:
            if await self._presets.slug_taken(wanted, org_id, excluding=excluding):
                raise ConflictError(f"'/{wanted}' is already taken in this organisation.")
            return wanted

        base = slugify(name)
        for attempt in range(1, _SLUG_ATTEMPTS + 1):
            candidate = base if attempt == 1 else f"{base}-{attempt}"
            if not await self._presets.slug_taken(candidate, org_id, excluding=excluding):
                return candidate
        raise ConflictError("Could not find a free slash command for that name.")

    async def _require_scope_permission(self, scope: PresetScope, user_id: uuid.UUID) -> None:
        """Widening a preset beyond yourself is an act with an audience.

        Private needs nothing. Anything the whole organisation will see needs
        someone the organisation has trusted with that.
        """
        if scope is PresetScope.PRIVATE:
            return
        await self._access.require_org_role(user_id, Role.TEAM_ADMIN)

    async def create(
        self, payload: PresetCreate, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> PresetResponse:
        await self._require_scope_permission(payload.scope, user_id)
        slug = await self._resolve_slug(payload.slug, payload.name, org_id)

        preset = await self._presets.add(
            Preset(
                org_id=org_id,
                created_by_user_id=user_id,
                name=payload.name,
                slug=slug,
                description=payload.description,
                system_prompt=payload.system_prompt,
                model_hint=payload.model_hint,
                scope=payload.scope,
                is_native=False,
                version=1,
            )
        )
        await self._presets.commit()
        # `created_at` and `updated_at` are server-generated, so they are not
        # on the instance until it is read back.
        await self._presets.refresh(preset)
        log.info("preset_created", preset=str(preset.id), slug=slug, scope=payload.scope.value)
        return await self._to_response(preset, user_id=user_id)

    async def update(
        self, preset_id: uuid.UUID, payload: PresetUpdate, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> PresetResponse:
        preset = await self._require_visible(preset_id, user_id, org_id)
        if not await self._may_edit(preset, user_id):
            raise PermissionDeniedError("This preset belongs to someone else.")

        if payload.scope is not None and payload.scope is not preset.scope:
            await self._require_scope_permission(payload.scope, user_id)
            preset.scope = payload.scope

        for field in ("name", "description", "system_prompt", "model_hint"):
            value = getattr(payload, field)
            if value is not None:
                setattr(preset, field, value)

        # Bumped on every accepted edit, so a conversation that recorded a
        # version can still say which text it actually ran under.
        preset.version += 1
        await self._presets.commit()
        await self._presets.refresh(preset)
        log.info("preset_updated", preset=str(preset.id), version=preset.version)
        return await self._to_response(preset, user_id=user_id)

    async def delete(self, preset_id: uuid.UUID, *, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
        preset = await self._require_visible(preset_id, user_id, org_id)
        if not await self._may_edit(preset, user_id):
            raise PermissionDeniedError("This preset belongs to someone else.")
        await self._presets.delete(preset)
        await self._presets.commit()
        log.info("preset_deleted", preset=str(preset_id))

    # --- pin, share, publish -------------------------------------------

    async def set_pinned(
        self, preset_id: uuid.UUID, *, pinned: bool, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> PresetResponse:
        preset = await self._require_visible(preset_id, user_id, org_id)
        await self._pins.set_pinned(user_id=user_id, preset_id=preset.id, pinned=pinned)
        await self._pins.commit()
        await self._presets.refresh(preset)
        return await self._to_response(preset, user_id=user_id)

    async def share(
        self,
        preset_id: uuid.UUID,
        *,
        recipient_id: uuid.UUID,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> PresetResponse:
        preset = await self._require_visible(preset_id, user_id, org_id)
        if not await self._may_edit(preset, user_id):
            raise PermissionDeniedError("Only the author can share this preset.")

        # The one operation that names another user. An id alone proves
        # nothing: without this, a private prompt could be handed to a stranger
        # in another tenant by pasting their id.
        recipient = await self._users.get(recipient_id)
        if recipient is None or recipient.org_id != org_id:
            raise NotFoundError("User not found.")
        if recipient_id == user_id:
            raise ValidationError("You already have this preset.")

        await self._shares.share(
            preset_id=preset.id, user_id=recipient_id, shared_by_user_id=user_id
        )
        await self._shares.commit()
        await self._presets.refresh(preset)
        log.info("preset_shared", preset=str(preset.id))
        return await self._to_response(preset, user_id=user_id)

    async def publish(
        self, preset_id: uuid.UUID, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> PresetResponse:
        """Offer a preset to the whole organisation."""
        preset = await self._require_visible(preset_id, user_id, org_id)
        if not await self._may_edit(preset, user_id):
            raise PermissionDeniedError("This preset belongs to someone else.")
        await self._require_scope_permission(PresetScope.PUBLISHED, user_id)

        preset.scope = PresetScope.PUBLISHED
        await self._presets.commit()
        await self._presets.refresh(preset)
        log.info("preset_published", preset=str(preset.id))
        return await self._to_response(preset, user_id=user_id)

    # --- what the composer needs ---------------------------------------

    async def resolve_slug(
        self, slug: str, *, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> Preset | None:
        """The slash command to its preset, or nothing.

        Returns the row rather than a response model: the caller is the chat
        path, which wants the prompt text, not something shaped for a client.
        """
        return await self._presets.get_by_slug(slug.lstrip("/").lower(), user_id, org_id)
