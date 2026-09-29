"""Blob storage behind a small interface, so the backend can move from Postgres to S3 later."""

import gzip
import hashlib
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edgeforge.raw.models import RawBlob


class BlobNotFoundError(KeyError):
    pass


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_key_for(data: bytes) -> str:
    return f"sha256/{content_hash(data)}"


class BlobStore(Protocol):
    def put(self, data: bytes) -> str:
        """Store ``data`` and return its content-addressed key. Idempotent."""
        ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


class InMemoryBlobStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        key = blob_key_for(data)
        self._blobs.setdefault(key, data)
        return key

    def get(self, key: str) -> bytes:
        try:
            return self._blobs[key]
        except KeyError:
            raise BlobNotFoundError(key) from None

    def exists(self, key: str) -> bool:
        return key in self._blobs


class PostgresBlobStore:
    """Stores gzip-compressed bodies in ``raw.raw_blob`` within the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def put(self, data: bytes) -> str:
        key = blob_key_for(data)
        self._session.execute(
            insert(RawBlob)
            .values(blob_key=key, body=gzip.compress(data, mtime=0))
            .on_conflict_do_nothing(index_elements=[RawBlob.blob_key])
        )
        return key

    def get(self, key: str) -> bytes:
        body = self._session.scalar(select(RawBlob.body).where(RawBlob.blob_key == key))
        if body is None:
            raise BlobNotFoundError(key)
        return gzip.decompress(body)

    def exists(self, key: str) -> bool:
        found = self._session.scalar(select(RawBlob.blob_key).where(RawBlob.blob_key == key))
        return found is not None
