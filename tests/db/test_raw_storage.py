import gzip
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import DataProvider, ProviderKind
from edgeforge.raw.blobstore import BlobNotFoundError, PostgresBlobStore
from edgeforge.raw.models import RawBlob, RawPayload
from edgeforge.raw.service import latest_payload, load_body, record_payload

pytestmark = pytest.mark.db

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
def provider(db_session: Session) -> DataProvider:
    provider = DataProvider(code="understat", kind=ProviderKind.STATS)
    db_session.add(provider)
    db_session.flush()
    return provider


def _record(
    session: Session, provider: DataProvider, body: bytes, at: datetime
) -> tuple[uuid.UUID, bool]:
    result = record_payload(
        session,
        PostgresBlobStore(session),
        provider_id=provider.id,
        resource="league",
        key="EPL/2026",
        url="https://understat.com/getLeagueData/EPL/2026",
        http_status=200,
        body=body,
        fetched_at=at,
    )
    return result.payload_id, result.changed


def test_postgres_blob_store_compresses_and_round_trips(db_session: Session) -> None:
    store = PostgresBlobStore(db_session)
    body = b'{"dates": []}' * 100

    key = store.put(body)
    store.put(body)

    stored = db_session.scalars(select(RawBlob).where(RawBlob.blob_key == key)).one()
    assert store.get(key) == body
    assert store.exists(key)
    assert gzip.decompress(stored.body) == body
    assert len(stored.body) < len(body)


def test_postgres_blob_store_missing_key(db_session: Session) -> None:
    with pytest.raises(BlobNotFoundError):
        PostgresBlobStore(db_session).get("sha256/missing")


def test_unchanged_payload_creates_no_new_row(db_session: Session, provider: DataProvider) -> None:
    first_id, first_changed = _record(db_session, provider, b'{"v": 1}', T0)
    second_id, second_changed = _record(db_session, provider, b'{"v": 1}', T0 + timedelta(hours=6))

    count = db_session.scalar(select(func.count()).select_from(RawPayload))
    assert (first_changed, second_changed) == (True, False)
    assert second_id == first_id
    assert count == 1


def test_changed_payload_supersedes_previous(db_session: Session, provider: DataProvider) -> None:
    first_id, _ = _record(db_session, provider, b'{"v": 1}', T0)
    second_id, changed = _record(db_session, provider, b'{"v": 2}', T0 + timedelta(hours=6))

    first = db_session.get(RawPayload, first_id)
    latest = latest_payload(db_session, provider.id, "league", "EPL/2026")
    assert changed is True
    assert first is not None
    assert first.superseded_by == second_id
    assert latest is not None
    assert latest.id == second_id
    assert load_body(PostgresBlobStore(db_session), latest) == b'{"v": 2}'


def test_reverting_content_is_recorded_as_a_new_version(
    db_session: Session, provider: DataProvider
) -> None:
    _record(db_session, provider, b'{"v": 1}', T0)
    _record(db_session, provider, b'{"v": 2}', T0 + timedelta(hours=1))
    third_id, changed = _record(db_session, provider, b'{"v": 1}', T0 + timedelta(hours=2))

    latest = latest_payload(db_session, provider.id, "league", "EPL/2026")
    blobs = db_session.scalar(select(func.count()).select_from(RawBlob))
    assert changed is True
    assert latest is not None
    assert latest.id == third_id
    assert blobs == 2


def test_rejects_naive_timestamp(db_session: Session, provider: DataProvider) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _record(db_session, provider, b"{}", datetime(2026, 9, 29))  # noqa: DTZ001
