"""Chooses the storage backend from configuration."""

from __future__ import annotations

from app.clients.storage.base import StorageClient
from app.clients.storage.local import LocalStorageClient
from app.clients.storage.s3 import S3StorageClient
from app.core.config import Settings


def build_storage_client(settings: Settings) -> StorageClient:
    if settings.storage_backend == "s3":
        return S3StorageClient(settings)
    return LocalStorageClient(settings.storage_local_path)
