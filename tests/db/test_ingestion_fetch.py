import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import DataProvider, ProviderKind
from edgeforge.ingestion.fetch import fetch_and_record
from edgeforge.providers.errors import ProviderBlockedError
from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload

pytestmark = pytest.mark.db

URL = "https://understat.com/getMatchData/26602"


def _fetcher(bodies: list[bytes]) -> HttpFetcher:
    queue = iter(bodies)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=next(queue)))
    )
    return HttpFetcher(client, RateLimiter(1000, burst=1000), sleep=lambda _: None)


def _provider(session: Session) -> DataProvider:
    provider = DataProvider(code="understat", kind=ProviderKind.STATS)
    session.add(provider)
    session.flush()
    return provider


def test_fetch_records_raw_payload_once_for_identical_content(db_session: Session) -> None:
    provider = _provider(db_session)
    fetcher = _fetcher([b'{"shots": 1}', b'{"shots": 1}'])
    store = PostgresBlobStore(db_session)

    def fetch() -> bool:
        return fetch_and_record(
            db_session,
            store,
            fetcher,
            provider_id=provider.id,
            resource="match",
            key="26602",
            url=URL,
        ).changed

    assert [fetch(), fetch()] == [True, False]
    payload = db_session.scalars(select(RawPayload)).one()
    assert payload.url == URL
    assert payload.http_status == 200
    assert store.get(payload.blob_key) == b'{"shots": 1}'


def test_blocked_response_stores_nothing(db_session: Session) -> None:
    provider = _provider(db_session)
    fetcher = _fetcher([b"<html>challenge</html>"])

    with pytest.raises(ProviderBlockedError):
        fetch_and_record(
            db_session,
            PostgresBlobStore(db_session),
            fetcher,
            provider_id=provider.id,
            resource="match",
            key="26602",
            url=URL,
        )

    assert db_session.scalar(select(func.count()).select_from(RawPayload)) == 0
