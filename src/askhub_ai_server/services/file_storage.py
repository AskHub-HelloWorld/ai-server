from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import urlparse

import boto3

from askhub_ai_server.core.config import Settings
from askhub_ai_server.models.file import UserFile


@dataclass(frozen=True)
class StoredFile:
    provider: str
    path: str
    bucket: str | None = None
    key: str | None = None


class FileStorage(Protocol):
    def save_file(
        self,
        fileobj: BinaryIO,
        *,
        user_id: int,
        file_id: uuid.UUID,
        filename: str,
        content_type: str | None,
    ) -> StoredFile: ...

    def read_bytes(self, user_file: UserFile, max_bytes: int) -> bytes: ...

    def delete_file(self, stored_file: StoredFile) -> None: ...

    def generate_download_url(self, user_file: UserFile, expires_in: int = 300) -> str: ...


class S3FileStorage:
    def __init__(self, settings: Settings) -> None:
        if not settings.s3_bucket:
            raise ValueError("S3_BUCKET is required when FILE_STORAGE_BACKEND=s3")
        self._bucket = settings.s3_bucket
        self._prefix = settings.s3_prefix.strip("/")
        self._client = boto3.client("s3", region_name=settings.s3_region)

    def save_file(
        self,
        fileobj: BinaryIO,
        *,
        user_id: int,
        file_id: uuid.UUID,
        filename: str,
        content_type: str | None,
    ) -> StoredFile:
        key = self._build_key(user_id=user_id, file_id=file_id, filename=filename)
        extra_args = {"ContentType": content_type} if content_type else None
        if extra_args:
            self._client.upload_fileobj(fileobj, self._bucket, key, ExtraArgs=extra_args)
        else:
            self._client.upload_fileobj(fileobj, self._bucket, key)
        return StoredFile(
            provider="s3",
            path=f"s3://{self._bucket}/{key}",
            bucket=self._bucket,
            key=key,
        )

    def read_bytes(self, user_file: UserFile, max_bytes: int) -> bytes:
        bucket = user_file.storage_bucket or self._bucket
        key = user_file.storage_key or _parse_s3_key(user_file.storage_path)
        if not key:
            raise FileNotFoundError(f"S3 object key is missing for file {user_file.id}")

        response = self._client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        try:
            return body.read(max_bytes)
        finally:
            body.close()

    def delete_file(self, stored_file: StoredFile) -> None:
        bucket = stored_file.bucket or self._bucket
        key = stored_file.key or _parse_s3_key(stored_file.path)
        if key:
            self._client.delete_object(Bucket=bucket, Key=key)

    def generate_download_url(self, user_file: UserFile, expires_in: int = 300) -> str:
        bucket = user_file.storage_bucket or self._bucket
        key = user_file.storage_key or _parse_s3_key(user_file.storage_path)
        if not key:
            raise FileNotFoundError(f"S3 object key is missing for file {user_file.id}")
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ResponseContentDisposition": f'inline; filename="{user_file.filename}"',
            },
            ExpiresIn=expires_in,
        )

    def _build_key(self, *, user_id: int, file_id: uuid.UUID, filename: str) -> str:
        safe_filename = Path(filename or "unknown").name
        key = f"{user_id}/{file_id}/{safe_filename}"
        return f"{self._prefix}/{key}" if self._prefix else key


def get_file_storage(settings: Settings) -> FileStorage:
    backend = settings.file_storage_backend.strip().lower()
    if backend == "s3":
        return S3FileStorage(settings)
    raise ValueError(f"unsupported FILE_STORAGE_BACKEND: {settings.file_storage_backend}")


def _parse_s3_key(storage_path: str | None) -> str | None:
    if not storage_path:
        return None
    parsed = urlparse(storage_path)
    if parsed.scheme != "s3":
        return None
    return parsed.path.lstrip("/")
