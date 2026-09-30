from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.app import create_app
from edgeforge.catalog.models import ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.football.teams import find_team
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
AS_OF = "2026-03-01T00:00:00Z"


@pytest.fixture
def client(db_connection: Connection, db_session: Session) -> Iterator[TestClient]:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)
    store = PostgresBlobStore(db_session)
    recorded = record_payload(
        db_session,
        store,
        provider_id=provider.id,
        resource="league",
        key="EPL/2025",
        url="https://understat.com/getLeagueData/EPL/2025",
        http_status=200,
        body=(FIXTURES / "league_EPL_2025.json").read_bytes(),
        fetched_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    normalize_league_payload(db_session, store, db_session.get_one(RawPayload, recorded.payload_id))
    db_session.flush()
    factory = sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")
    with TestClient(create_app(factory)) as test_client:
        yield test_client


def test_competitions(client: TestClient) -> None:
    response = client.get("/api/competitions")

    assert response.status_code == 200
    assert response.json() == [{"code": "EPL", "name": "Premier League", "country": "England"}]


def test_fixtures_in_window(client: TestClient) -> None:
    response = client.get("/api/competitions/EPL/fixtures", params={"days": 7, "as_of": AS_OF})

    fixtures = response.json()
    assert response.status_code == 200
    assert fixtures
    kickoffs = [f["kickoff_at"] for f in fixtures]
    assert kickoffs == sorted(kickoffs)
    assert all("2026-03-01" <= k < "2026-03-08" for k in kickoffs)
    assert all(f["home"]["name"] and f["away"]["name"] for f in fixtures)


def test_teams(client: TestClient) -> None:
    names = [t["name"] for t in client.get("/api/competitions/EPL/teams").json()]

    assert len(names) == 20
    assert names == sorted(names)
    assert "Arsenal" in names


def test_compare(client: TestClient, db_session: Session) -> None:
    arsenal, chelsea = find_team(db_session, "Arsenal"), find_team(db_session, "Chelsea")

    response = client.get(
        "/api/competitions/EPL/compare",
        params={"home": str(arsenal), "away": str(chelsea), "last": [5, 10], "as_of": AS_OF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["home"]["team"]["name"] == "Arsenal"
    assert body["away"]["team"]["name"] == "Chelsea"
    assert [w["last"] for w in body["home"]["form"]] == [5, 10]
    assert body["home"]["form"][1]["overall"]["matches"] == 10
    assert len(body["home"]["recent"]) == 10
    assert all(m["kickoff_at"] < AS_OF for m in body["home"]["recent"] + body["head_to_head"])
    assert all(m["result"] in "WDL" for m in body["away"]["recent"])
    for meeting in body["head_to_head"]:
        assert {meeting["home"]["name"], meeting["away"]["name"]} == {"Arsenal", "Chelsea"}
    estimate = body["estimate"]
    assert estimate["home_win"] + estimate["draw"] + estimate["away_win"] == pytest.approx(1)


def test_compare_rejects_bad_requests(client: TestClient, db_session: Session) -> None:
    arsenal = str(find_team(db_session, "Arsenal"))
    url = "/api/competitions/EPL/compare"

    same = client.get(url, params={"home": arsenal, "away": arsenal})
    assert same.status_code == 422
    unknown_team = client.get(url, params={"home": arsenal, "away": arsenal[:-1] + "0"})
    assert unknown_team.status_code == 404
    bad_window = client.get(
        url, params={"home": arsenal, "away": str(find_team(db_session, "Chelsea")), "last": 0}
    )
    assert bad_window.status_code == 422
    assert client.get("/api/competitions/XX/teams").status_code == 404
