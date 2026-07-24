"""Storage backends for user-controlled attachments.

The API never exposes a storage path to the browser.  Attachment access always
goes through the workspace authorization checks in ``api.routes``.  Local disk
is useful for development; the S3-compatible backend gives deployments a
durable object-store path without changing the product API.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from config import settings


class StorageError(RuntimeError):
    """A storage operation failed without exposing provider details to users."""


class ObjectNotFound(StorageError):
    """The requested object does not exist in the configured storage."""


def attachment_object_key(workspace_id: str, filename: str) -> str:
    """Build a tenant-scoped, provider-neutral object key."""
    return f"workspaces/{workspace_id}/{filename}"


def _validated_key(key: str) -> str:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise StorageError("Invalid attachment storage key")
    return path.as_posix()


class StorageBackend(ABC):
    """Small common contract shared by local and S3-compatible object stores."""

    @abstractmethod
    def put_stream(self, key: str, source: BinaryIO, *, content_type: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def open_stream(self, key: str) -> BinaryIO:
        """Return a readable stream. The caller is responsible for closing it."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def check_ready(self) -> None:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    """Atomic local-file backend for development and single-node deployments."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        target = (self.root / _validated_key(key)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise StorageError("Attachment path escapes the storage root") from exc
        return target

    def put_stream(self, key: str, source: BinaryIO, *, content_type: str) -> None:
        del content_type
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as destination_file:
                shutil.copyfileobj(source, destination_file, length=1024 * 1024)
            Path(temporary_name).replace(destination)
        except OSError as exc:
            Path(temporary_name).unlink(missing_ok=True)
            raise StorageError("Could not save attachment") from exc

    def open_stream(self, key: str) -> BinaryIO:
        try:
            return self._path(key).open("rb")
        except FileNotFoundError as exc:
            raise ObjectNotFound("Attachment object is unavailable") from exc
        except OSError as exc:
            raise StorageError("Could not read attachment") from exc

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("Could not delete attachment") from exc

    def check_ready(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.is_dir():
                raise StorageError("Local storage root is not a directory")
        except OSError as exc:
            raise StorageError("Local attachment storage is unavailable") from exc


class S3Storage(StorageBackend):
    """S3-compatible backend, including MinIO and managed object stores.

    ``boto3`` is intentionally imported only when this backend is selected so
    a local developer does not need cloud credentials or a running object
    store.  The deployment image installs the dependency from requirements.
    """

    def __init__(self) -> None:
        if not settings.storage_s3_bucket:
            raise StorageError("STORAGE_S3_BUCKET is required for S3 storage")
        if not settings.storage_s3_access_key_id or not settings.storage_s3_secret_access_key:
            raise StorageError("S3 storage credentials are not configured")
        self.bucket = settings.storage_s3_bucket
        self.prefix = settings.storage_s3_prefix.strip("/")
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - covered by container build
            raise StorageError("S3 storage support is not installed") from exc
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.storage_s3_endpoint_url or None,
            region_name=settings.storage_s3_region or None,
            aws_access_key_id=settings.storage_s3_access_key_id,
            aws_secret_access_key=settings.storage_s3_secret_access_key,
            config=Config(s3={"addressing_style": settings.storage_s3_addressing_style}),
        )

    def _key(self, key: str) -> str:
        key = _validated_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_stream(self, key: str, source: BinaryIO, *, content_type: str) -> None:
        try:
            self.client.upload_fileobj(
                source,
                self.bucket,
                self._key(key),
                ExtraArgs={"ContentType": content_type},
            )
        except Exception as exc:  # Provider exceptions must not leak through the API.
            raise StorageError("Could not save attachment to object storage") from exc

    def open_stream(self, key: str) -> BinaryIO:
        # Spooled storage avoids holding a potentially large historical object in RAM.
        stream = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode="w+b")
        try:
            self.client.download_fileobj(self.bucket, self._key(key), stream)
            stream.seek(0)
            return stream
        except Exception as exc:
            stream.close()
            response = getattr(exc, "response", {})
            error_code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if str(error_code) in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectNotFound("Attachment object is unavailable") from exc
            raise StorageError("Could not read attachment from object storage") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
        except Exception as exc:
            raise StorageError("Could not delete attachment from object storage") from exc

    def check_ready(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            raise StorageError("Object storage is unavailable") from exc


def get_storage() -> StorageBackend:
    backend = settings.storage_backend.strip().lower()
    if backend == "local":
        return LocalStorage(settings.upload_dir)
    if backend == "s3":
        return S3Storage()
    raise StorageError("Unsupported STORAGE_BACKEND; use 'local' or 's3'")
