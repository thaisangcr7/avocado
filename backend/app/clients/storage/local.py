"""Filesystem-backed storage for local development.

Config rejects this backend outside development — it is not shared between
processes or hosts, so a deployed API and worker would not see the same files.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.clients.storage.base import StorageClient
from app.core.errors import NotFoundError


class LocalStorageClient(StorageClient):
    name = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Resolve and confirm containment: a key with `..` must not escape the
        # storage root.
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return candidate

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return key

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise NotFoundError("Stored object not found.")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def _unlink() -> None:
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_unlink)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)
