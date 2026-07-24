"""Abstract file storage — local filesystem for dev, S3-compatible for production.

Dev: files stored under ./storage/invoices/{user_id}/{invoice_id}.jpg
Prod: files stored in S3/R2 bucket under invoices/{user_id}/{invoice_id}.jpg

No file is stored in MongoDB. Only the storage key is referenced in the invoice
document. This keeps MongoDB small (< 500MB) even at 10K users x 100 invoices.
"""

import os
import pathlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_STORAGE_DIR = pathlib.Path(os.getenv("LOCAL_STORAGE_DIR", "./storage"))


def _get_s3_client():
    """Lazy-import aioboto3 and create a session."""
    import aioboto3
    return aioboto3.Session(
        aws_access_key_id=os.getenv("S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        region_name=os.getenv("S3_REGION", "auto"),
    )


def _bucket() -> str:
    return os.getenv("S3_BUCKET", "invosync-invoices")


def _endpoint() -> Optional[str]:
    return os.getenv("S3_ENDPOINT") or os.getenv("AWS_ENDPOINT_URL") or None


def _use_s3() -> bool:
    return bool(os.getenv("S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")) and bool(
        os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET")
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def key_for(user_id: str, invoice_id: int) -> str:
    """Return the storage key (path) for a given invoice image."""
    return f"invoices/{user_id}/{invoice_id}.jpg"


async def store(user_id: str, invoice_id: int, image_bytes: bytes) -> str:
    """Store an invoice image. Returns the storage key.

    Uses S3-compatible storage in production, local filesystem in dev.
    """
    storage_key = key_for(user_id, invoice_id)
    if _use_s3():
        await _store_s3(storage_key, image_bytes)
    else:
        await _store_local(storage_key, image_bytes)
    return storage_key


async def retrieve(storage_key: str) -> Optional[bytes]:
    """Retrieve image bytes by storage key. Returns None if not found."""
    if _use_s3():
        return await _retrieve_s3(storage_key)
    return await _retrieve_local(storage_key)


async def delete(storage_key: str) -> None:
    """Delete an invoice image by storage key. No-op if not found."""
    if _use_s3():
        await _delete_s3(storage_key)
    else:
        await _delete_local(storage_key)


# ---------------------------------------------------------------------------
# Local filesystem backend (dev)
# ---------------------------------------------------------------------------

async def _store_local(storage_key: str, image_bytes: bytes) -> None:
    path = _STORAGE_DIR / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)


async def _retrieve_local(storage_key: str) -> Optional[bytes]:
    path = _STORAGE_DIR / storage_key
    if not path.exists():
        return None
    return path.read_bytes()


async def _delete_local(storage_key: str) -> None:
    path = _STORAGE_DIR / storage_key
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# S3-compatible backend (R2 / S3 / MinIO)
# ---------------------------------------------------------------------------

async def _store_s3(storage_key: str, image_bytes: bytes) -> None:
    session = _get_s3_client()
    async with session.client("s3", endpoint_url=_endpoint()) as s3:
        bucket = _bucket()
        await s3.create_bucket(Bucket=bucket)
        await s3.put_object(
            Bucket=bucket,
            Key=storage_key,
            Body=image_bytes,
            ContentType="image/jpeg",
        )


async def _retrieve_s3(storage_key: str) -> Optional[bytes]:
    session = _get_s3_client()
    async with session.client("s3", endpoint_url=_endpoint()) as s3:
        try:
            obj = await s3.get_object(Bucket=_bucket(), Key=storage_key)
            return await obj["Body"].read()
        except s3.exceptions.NoSuchKey:
            return None


async def _delete_s3(storage_key: str) -> None:
    session = _get_s3_client()
    async with session.client("s3", endpoint_url=_endpoint()) as s3:
        try:
            await s3.delete_object(Bucket=_bucket(), Key=storage_key)
        except Exception:
            pass
