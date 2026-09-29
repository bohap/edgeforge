"""Fetch one provider resource and record it in the raw layer."""

import uuid
from collections.abc import Mapping

from sqlalchemy.orm import Session

from edgeforge.providers.http import HttpFetcher
from edgeforge.raw.blobstore import BlobStore
from edgeforge.raw.service import RecordResult, record_payload


def fetch_and_record(
    session: Session,
    store: BlobStore,
    fetcher: HttpFetcher,
    *,
    provider_id: uuid.UUID,
    resource: str,
    key: str,
    url: str,
    headers: Mapping[str, str] | None = None,
) -> RecordResult:
    """Fetch ``url`` and store the body. Provider errors propagate; nothing is stored then."""
    result = fetcher.get(url, headers=headers)
    return record_payload(
        session,
        store,
        provider_id=provider_id,
        resource=resource,
        key=key,
        url=result.url,
        http_status=result.status,
        body=result.body,
        fetched_at=result.fetched_at,
    )
