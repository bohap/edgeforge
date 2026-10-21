import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import ProviderEntityMap, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.football.teams import find_team
from edgeforge.ingestion import polymarket
from edgeforge.marketdata.models import MarketQuote
from edgeforge.providers.http import HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LISTING = json.loads((FIXTURES / "polymarket" / "listing_EPL.json").read_bytes())
EVENTS = json.loads((FIXTURES / "polymarket" / "events_EPL.json").read_bytes())
NOW = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
IPS_NOT = "epl-ips-not-2026-10-23"


@pytest.fixture
def season(db_session: Session) -> Session:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)
    store = PostgresBlobStore(db_session)
    recorded = record_payload(
        db_session,
        store,
        provider_id=provider.id,
        resource="league",
        key="EPL/2026",
        url="https://understat.com/getLeagueData/EPL/2026",
        http_status=200,
        body=(FIXTURES / "understat" / "league_EPL_2026.json").read_bytes(),
        fetched_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    normalize_league_payload(db_session, store, db_session.get_one(RawPayload, recorded.payload_id))
    return db_session


def _fetcher(
    price_shift: float = 0.0, rename: dict[str, str] | None = None
) -> tuple[HttpFetcher, list[str]]:
    requested: list[str] = []
    rename = rename or {}

    def adjust(event: dict[str, object]) -> dict[str, object]:
        event = json.loads(json.dumps(event))
        for team in event["teams"]:  # type: ignore[attr-defined]
            if team["name"] in rename:
                team["name"] = team["alias"] = rename[team["name"]]
        for market in event.get("markets", []):  # type: ignore[attr-defined]
            if market["bestAsk"] is not None:
                market["bestAsk"] = round(market["bestAsk"] + price_shift, 4)
        return event

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        query = parse_qs(urlparse(str(request.url)).query)
        if "series_id" in query:
            page = LISTING if query["offset"] == ["0"] else []
            return httpx.Response(200, json=[adjust(e) for e in page])
        slugs = set(query["slug"])
        return httpx.Response(200, json=[adjust(e) for e in EVENTS if e["slug"] in slugs])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpFetcher(client, RateLimiter(1000, burst=1000), sleep=lambda _: None), requested


def _quotes(session: Session, slug_prefix: str) -> dict[tuple[str, str, str], MarketQuote]:
    rows = session.scalars(
        select(MarketQuote).where(MarketQuote.event_slug.startswith(slug_prefix))
    ).all()
    return {(q.market_code, q.params_key, q.outcome): q for q in rows}


def test_games_are_matched_and_quotes_stored(season: Session) -> None:
    fetcher, requested = _fetcher()

    result = polymarket.ingest_league(season, fetcher, "EPL", NOW)

    # The listing has the week's games; the fixture only carries full markets for three.
    assert result.games == 10
    assert result.matched == 3
    assert result.unmatched == []
    assert result.skipped_markets == 0
    assert any("include_markets=false" in url for url in requested)
    quotes = _quotes(season, IPS_NOT)
    assert len(quotes) == 35
    over = quotes[("TOTAL_GOALS", "line=2.5", "OVER")]
    assert (over.best_bid, over.best_ask, over.fee_rate) == (0.54, 0.55, 0.05)
    assert over.params == {"line": 2.5}
    assert over.event_slug == f"{IPS_NOT}-more-markets"
    home = quotes[("MATCH_RESULT", "", "HOME")]
    assert home.event_slug == IPS_NOT
    assert home.match_id == season.scalar(
        select(ProviderEntityMap.internal_id).where(ProviderEntityMap.external_id == IPS_NOT)
    )
    assert season.scalar(
        select(ProviderEntityMap.internal_id).where(
            ProviderEntityMap.external_id == "Nottingham Forest FC"
        )
    ) == find_team(season, "Nottingham Forest")


def test_rerun_reuses_mappings_and_updates_prices(season: Session) -> None:
    polymarket.ingest_league(season, _fetcher()[0], "EPL", NOW)
    mappings = season.scalar(select(func.count()).select_from(ProviderEntityMap))

    later = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
    result = polymarket.ingest_league(season, _fetcher(price_shift=0.01)[0], "EPL", later)

    assert result.matched == 3
    assert season.scalar(select(func.count()).select_from(ProviderEntityMap)) == mappings
    over = _quotes(season, IPS_NOT)[("TOTAL_GOALS", "line=2.5", "OVER")]
    assert over.best_ask == pytest.approx(0.56)
    assert over.observed_at == later


def test_prices_freeze_at_kickoff(season: Session) -> None:
    polymarket.ingest_league(season, _fetcher()[0], "EPL", NOW)

    # Ipswich v Forest kicked off at 19:00; the other two games are on the 24th.
    after_kickoff = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
    polymarket.ingest_league(season, _fetcher(price_shift=0.02)[0], "EPL", after_kickoff)

    frozen = _quotes(season, IPS_NOT)[("TOTAL_GOALS", "line=2.5", "OVER")]
    assert frozen.best_ask == pytest.approx(0.55)
    moved = _quotes(season, "epl-ars-eve-2026-10-24")[("MATCH_RESULT", "", "HOME")]
    assert moved.observed_at == after_kickoff


def test_unknown_teams_are_reported_not_guessed(season: Session) -> None:
    rename = {"Ipswich Town FC": "Atlantis FC", "Nottingham Forest FC": "Lemuria United"}

    result = polymarket.ingest_league(season, _fetcher(rename=rename)[0], "EPL", NOW)

    assert result.matched == 2
    assert result.unmatched == ["Ipswich Town FC vs. Nottingham Forest FC"]
    assert _quotes(season, IPS_NOT) == {}


def test_leagues_without_our_data_are_skipped(db_session: Session) -> None:
    fetcher, requested = _fetcher()

    assert polymarket.ingest_league(db_session, fetcher, "EPL", NOW).games == 0
    assert requested == []
    assert polymarket.leagues_with_data(db_session) == []
    assert polymarket.enqueue_league(db_session, "NOT_A_LEAGUE") is None
