"""Object storage contract.

Storage keys are always workspace-prefixed (`workspaces/{id}/...`) so a bucket
listing is tenant-partitioned and an accidental cross-tenant key is visible on
inspection rather than hidden in a flat namespace.
"""

from __future__ import annotations

import abc
import uuid


def build_storage_key(
    workspace_id: uuid.UUID, category: str, identifier: str, filename: str
) -> str:
    safe = filename.replace("/", "_").replace("\\", "_")[:200]
    return f"workspaces/{workspace_id}/{category}/{identifier}/{safe}"


class StorageClient(abc.ABC):
    name: str

    @abc.abstractmethod
    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        """Store bytes and return the key."""

    @abc.abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def exists(self, key: str) -> bool: ...
