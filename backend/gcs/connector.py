from config import GCS_BUCKET_NAME as BUCKET_NAME
from google.cloud import storage
import os
from typing import Optional


def _client() -> storage.Client:
    return storage.Client()


def list_files(prefix: str = "", bucket_name: str = BUCKET_NAME) -> list[str]:
    """List all blob names under *prefix* in the bucket."""
    blobs = _client().list_blobs(bucket_name, prefix=prefix)
    return [blob.name for blob in blobs]


def read_file(path: str, bucket_name: str = BUCKET_NAME) -> bytes:
    """Download a blob and return its raw bytes."""
    return _client().bucket(bucket_name).blob(path).download_as_bytes()


def read_text(
    path: str, bucket_name: str = BUCKET_NAME, encoding: str = "utf-8"
) -> str:
    """Download a text blob and return it as a string."""
    return read_file(path, bucket_name).decode(encoding)


def write_file(
    path: str,
    data: bytes | str,
    content_type: str = "application/octet-stream",
    bucket_name: str | None = None, # Change default to None
) -> str:
    # Fallback to the environment variable if no name is provided
    if bucket_name is None:
        bucket_name = os.getenv("BUCKET_NAME", "").strip().strip("/")

    if isinstance(data, str):
        data = data.encode("utf-8")
    
    # This is where the "Bucket names must start/end..." error is thrown
    blob = _client().bucket(bucket_name).blob(path)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{bucket_name}/{path}"


def delete_file(path: str, bucket_name: str = BUCKET_NAME) -> None:
    """Delete the blob at *path*."""
    _client().bucket(bucket_name).blob(path).delete()


def file_exists(path: str, bucket_name: str = BUCKET_NAME) -> bool:
    """Return True if the blob exists."""
    return _client().bucket(bucket_name).blob(path).exists()
