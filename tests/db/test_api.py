from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.app import create_app
from edgeforge.catalog.models import ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.features.gateway import upcoming_fixtures
from edgeforge.football.teams import find_team
from edgeforge.marketdata.models import MarketQuote
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


def test_compare_includes_polymarket_prices(client: TestClient, db_session: Session) -> None:
    as_of = datetime(2026, 3, 1, tzinfo=UTC)
    fixture = upcoming_fixtures(db_session, as_of, as_of + timedelta(days=14))[0]
    provider = ensure_provider(db_session, "polymarket", ProviderKind.MARKET)
    raw = record_payload(
        db_session,
        PostgresBlobStore(db_session),
        provider_id=provider.id,
        resource="events",
        key="games/EPL/0",
        url="https://gamma-api.polymarket.com/events",
        http_status=200,
        body=b"[]",
        fetched_at=as_of - timedelta(hours=1),
    )
    for code, params, outcome, bid, ask, slug in (
        ("MATCH_RESULT", {}, "HOME", 0.44, 0.45, "epl-x-y"),
        ("TOTAL_GOALS", {"line": 2.5}, "OVER", 0.54, 0.56, "epl-x-y-more-markets"),
        ("TOTAL_GOALS", {"line": 7.5}, "OVER", None, 0.5, "epl-x-y-more-markets"),
    ):
        db_session.add(
            MarketQuote(
                match_id=fixture.match_id,
                provider_id=provider.id,
                market_code=code,
                params_key=";".join(f"{k}={v}" for k, v in sorted(params.items())),
                outcome=outcome,
                params=params,
                best_bid=bid,
                best_ask=ask,
                last_price=None,
                liquidity=500.0,
                fee_rate=0.05,
                external_id="0xabc",
                event_slug=slug,
                source_raw_id=raw.payload_id,
                observed_at=as_of - timedelta(hours=1),
            )
        )
    db_session.flush()

    body = client.get(
        "/api/competitions/EPL/compare",
        params={
            "home": str(fixture.home_team_id),
            "away": str(fixture.away_team_id),
            "as_of": as_of.isoformat(),
        },
    ).json()

    assert body["kickoff_at"] == fixture.kickoff_at.isoformat().replace("+00:00", "Z")
    pm = body["polymarket"]
    assert pm["url"] == "https://polymarket.com/event/epl-x-y"
    sides = {(s["market_code"], s["outcome"], s["negated"]): s for s in pm["sides"]}
    assert set(sides) == {
        ("MATCH_RESULT", "HOME", False),
        ("MATCH_RESULT", "HOME", True),
        ("TOTAL_GOALS", "OVER", False),
        ("TOTAL_GOALS", "OVER", True),
    }  # the 7.5 line has no bid, so no usable price
    over = sides[("TOTAL_GOALS", "OVER", False)]
    assert over["url"] == "https://polymarket.com/event/epl-x-y-more-markets"
    assert over["market_probability"] == pytest.approx(0.55)
    assert 0 < over["model_probability"] < 1
    assert over["edge"] == pytest.approx(over["model_probability"] * over["odds"] - 1)

    earlier = client.get(
        "/api/competitions/EPL/compare",
        params={
            "home": str(fixture.home_team_id),
            "away": str(fixture.away_team_id),
            "as_of": (as_of - timedelta(hours=2)).isoformat(),
        },
    ).json()
    assert earlier["polymarket"] is None  # the quotes were not known yet
