from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from fastapi import UploadFile

from ..settings import settings


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class LocalStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_filename(filename: str | None, fallback: str = "upload.bin") -> str:
        cleaned = SAFE_NAME.sub("_", Path(filename or fallback).name).strip("._")
        return cleaned or fallback

    def absolute(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("Unsafe storage path")
        return path

    async def save_upload(self, storage_key: str, upload: UploadFile) -> tuple[str, int]:
        path = self.absolute(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        limit = settings.max_upload_mb * 1024 * 1024

        with path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    target.close()
                    path.unlink(missing_ok=True)
                    raise ValueError(f"File exceeds {settings.max_upload_mb} MB")
                digest.update(chunk)
                target.write(chunk)

        return digest.hexdigest(), total

    def save_bytes(self, storage_key: str, data: bytes) -> str:
        path = self.absolute(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def persist_file(self, storage_key: str, path: Path) -> None:
        target = self.absolute(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)

    def delete_key(self, storage_key: str) -> None:
        self.absolute(storage_key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        path = self.absolute(prefix)
        if path.exists():
            shutil.rmtree(path)


class S3Storage(LocalStorage):
    """Private S3 storage with a local disposable cache.

    References and generated files are persisted in S3. API and worker containers may
    have separate filesystems: missing files are downloaded to the local cache on demand.
    """

    def __init__(self) -> None:
        super().__init__(settings.storage_root)
        import boto3
        from botocore.config import Config

        if not all(
            [
                settings.s3_endpoint_url,
                settings.s3_bucket,
                settings.s3_access_key,
                settings.s3_secret_key,
            ]
        ):
            raise RuntimeError("S3 storage is selected, but S3 settings are incomplete")
        self.bucket = str(settings.s3_bucket)
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 5, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )

    def absolute(self, storage_key: str) -> Path:
        path = super().absolute(storage_key)
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, storage_key, str(path))
        except Exception as exc:  # boto3 has multiple backend-specific not-found exceptions
            path.unlink(missing_ok=True)
            response = getattr(exc, "response", {}) or {}
            code = str((response.get("Error") or {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise
        return path

    async def save_upload(self, storage_key: str, upload: UploadFile) -> tuple[str, int]:
        digest, total = await super().save_upload(storage_key, upload)
        self.client.upload_file(str(super().absolute(storage_key)), self.bucket, storage_key)
        return digest, total

    def save_bytes(self, storage_key: str, data: bytes) -> str:
        digest = super().save_bytes(storage_key, data)
        self.client.upload_file(str(super().absolute(storage_key)), self.bucket, storage_key)
        return digest

    def persist_file(self, storage_key: str, path: Path) -> None:
        target = super().absolute(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        self.client.upload_file(str(target), self.bucket, storage_key)

    def delete_key(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)
        super().delete_key(storage_key)

    def delete_prefix(self, prefix: str) -> None:
        continuation: str | None = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            response = self.client.list_objects_v2(**kwargs)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True})
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
        super().delete_prefix(prefix)


storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage()
