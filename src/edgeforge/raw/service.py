"""Recording provider payloads. Unchanged content creates no new rows."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.raw.blobstore import BlobStore, content_hash
from edgeforge.raw.models import RawPayload


@dataclass(frozen=True, slots=True)
class RecordResult:
    payload_id: uuid.UUID
    changed: bool


def latest_payload(
    session: Session, provider_id: uuid.UUID, resource: str, key: str
) -> RawPayload | None:
    return session.scalars(
        select(RawPayload)
        .where(
            RawPayload.provider_id == provider_id,
            RawPayload.resource == resource,
            RawPayload.key == key,
            RawPayload.superseded_by.is_(None),
        )
        .order_by(RawPayload.fetched_at.desc())
        .limit(1)
    ).first()


def record_payload(
    session: Session,
    store: BlobStore,
    *,
    provider_id: uuid.UUID,
    resource: str,
    key: str,
    url: str,
    http_status: int,
    body: bytes,
    fetched_at: datetime,
) -> RecordResult:
    """Store a fetched body. Returns ``changed=False`` if it matches the latest stored version."""
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")

    digest = content_hash(body)
    previous = latest_payload(session, provider_id, resource, key)
    if previous is not None and previous.content_hash == digest:
        return RecordResult(payload_id=previous.id, changed=False)

    payload = RawPayload(
        provider_id=provider_id,
        resource=resource,
        key=key,
        url=url,
        http_status=http_status,
        fetched_at=fetched_at,
        content_hash=digest,
        blob_key=store.put(body),
        bytes=len(body),
    )
    session.add(payload)
    session.flush()
    if previous is not None:
        previous.superseded_by = payload.id
        session.flush()
    return RecordResult(payload_id=payload.id, changed=True)


def load_body(store: BlobStore, payload: RawPayload) -> bytes:
    return store.get(payload.blob_key)
