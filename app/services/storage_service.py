"""
MinIO storage service — file upload, download, presigned URLs.
"""

import io
from datetime import timedelta
from typing import Optional

from loguru import logger
from minio import Minio
from minio.error import S3Error

from app.config import settings


class StorageService:
    """S3-compatible object storage via MinIO."""

    def __init__(self):
        self._client: Optional[Minio] = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    async def ensure_bucket(self):
        """Create the default bucket if it doesn't exist."""
        bucket = settings.minio_bucket
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: {bucket}")
            else:
                logger.debug(f"MinIO bucket already exists: {bucket}")
        except S3Error as e:
            logger.error(f"Failed to ensure MinIO bucket: {e}")
            raise

    def upload_file(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to MinIO. Returns the object key."""
        bucket = settings.minio_bucket
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.debug(f"Uploaded {object_name} to MinIO ({len(data)} bytes)")
        return object_name

    def download_file(self, object_name: str) -> bytes:
        """Download a file from MinIO and return its bytes."""
        bucket = settings.minio_bucket
        response = None
        try:
            response = self.client.get_object(bucket, object_name)
            return response.read()
        finally:
            if response:
                response.close()
                response.release_conn()

    def upload_stream(
        self,
        object_name: str,
        stream: io.IOBase,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload from a stream."""
        bucket = settings.minio_bucket
        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=stream,
            length=length,
            content_type=content_type,
        )
        return object_name

    def get_presigned_url(
        self,
        object_name: str,
        expiry_hours: Optional[int] = None,
    ) -> str:
        """Generate a presigned download URL."""
        hours = expiry_hours or settings.minio_presign_expiry_hours
        url = self.client.presigned_get_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            expires=timedelta(hours=hours),
        )
        return url

    def delete_object(self, object_name: str):
        """Delete a file from MinIO."""
        self.client.remove_object(settings.minio_bucket, object_name)
        logger.debug(f"Deleted {object_name} from MinIO")

    def delete_prefix(self, prefix: str):
        """Delete all objects with a given prefix (e.g. a source's files)."""
        objects = self.client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)
        for obj in objects:
            self.client.remove_object(settings.minio_bucket, obj.object_name)
        logger.debug(f"Deleted all objects with prefix: {prefix}")


# Singleton
storage_service = StorageService()
