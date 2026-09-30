from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.catalog.models import DataProvider, ProviderEntityMap, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.cli import main as cli_main
from edgeforge.football.models import Match, Team
from edgeforge.ingestion.football_data import SEASON_TASK, enqueue_season, ingest_season
from edgeforge.marketdata.models import HistoricalOdds
from edgeforge.providers.football_data_uk.client import RESOURCE, SeasonRef
from edgeforge.providers.football_data_uk.normalize import (
    OddsNormalizeStats,
    normalize_season_payload,
)
from edgeforge.providers.football_data_uk.parser import parse_season_csv
from edgeforge.providers.http import FetchPolicy, HttpFetcher
from edgeforge.providers.ratelimit import RateLimiter
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CSV = (FIXTURES / "football_data_uk" / "E0_2526.csv").read_bytes()
FETCHED = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def _record(
    session: Session, provider: DataProvider, resource: str, key: str, body: bytes
) -> RawPayload:
    result = record_payload(
        session,
        PostgresBlobStore(session),
        provider_id=provider.id,
        resource=resource,
        key=key,
        url=f"https://example/{key}",
        http_status=200,
        body=body,
        fetched_at=FETCHED,
    )
    return session.get_one(RawPayload, result.payload_id)


@pytest.fixture
def odds_provider(db_session: Session) -> DataProvider:
    understat = ensure_provider(db_session, "understat", ProviderKind.STATS)
    league = _record(
        db_session,
        understat,
        "league",
        "EPL/2025",
        (FIXTURES / "understat" / "league_EPL_2025.json").read_bytes(),
    )
    normalize_league_payload(db_session, PostgresBlobStore(db_session), league)
    return ensure_provider(db_session, "football_data_uk", ProviderKind.ODDS)


def _normalize(session: Session, provider: DataProvider, body: bytes = CSV) -> OddsNormalizeStats:
    payload = _record(session, provider, RESOURCE, "EPL/2025", body)
    return normalize_season_payload(session, PostgresBlobStore(session), payload)


def test_parser_reads_times_as_uk_local() -> None:
    rows = parse_season_csv(CSV)
    first = rows[0]

    assert len(rows) == 380
    assert (first.home_team, first.away_team) == ("Liverpool", "Bournemouth")
    assert first.match_date == date(2025, 8, 15)
    assert first.kickoff_at == datetime(2025, 8, 15, 19, 0, tzinfo=UTC)  # 20:00 BST
    assert (first.home_goals, first.away_goals) == (4, 2)


def test_season_url() -> None:
    assert SeasonRef("EPL", 2025).url == "https://football-data.co.uk/mmz4281/2526/E0.csv"
    assert SeasonRef("LA_LIGA", 2021).url == "https://football-data.co.uk/mmz4281/2122/SP1.csv"


def test_every_row_is_matched_and_every_name_resolved(
    db_session: Session, odds_provider: DataProvider
) -> None:
    stats = _normalize(db_session, odds_provider)

    assert stats.as_dict() == {
        "rows": 380,
        "matched": 380,
        "unmatched": 0,
        "teams_mapped": 20,
        "unresolved_names": [],
    }


@pytest.mark.parametrize(
    ("provider_name", "understat_name"),
    [
        ("Wolves", "Wolverhampton Wanderers"),
        ("Man City", "Manchester City"),
        ("Man United", "Manchester United"),
        ("Nott'm Forest", "Nottingham Forest"),
        ("Newcastle", "Newcastle United"),
    ],
)
def test_names_resolve_to_the_right_team(
    db_session: Session, odds_provider: DataProvider, provider_name: str, understat_name: str
) -> None:
    _normalize(db_session, odds_provider)

    mapped = db_session.scalar(
        select(Team.name)
        .join(ProviderEntityMap, ProviderEntityMap.internal_id == Team.id)
        .where(
            ProviderEntityMap.provider_id == odds_provider.id,
            ProviderEntityMap.external_id == provider_name,
        )
    )
    assert mapped == understat_name


def test_odds_are_stored_per_bookmaker_market_and_outcome(
    db_session: Session, odds_provider: DataProvider
) -> None:
    _normalize(db_session, odds_provider)
    liverpool = db_session.scalars(select(Team.id).where(Team.name == "Liverpool")).one()
    match_id = db_session.scalars(
        select(Match.id).where(
            Match.home_team_id == liverpool,
            Match.kickoff_at == datetime(2025, 8, 15, 19, 0, tzinfo=UTC),
        )
    ).one()

    odds = {
        (o.bookmaker, o.market_code, o.outcome): (o.opening, o.closing)
        for o in db_session.scalars(
            select(HistoricalOdds).where(HistoricalOdds.match_id == match_id)
        )
    }

    assert odds[("bet365", "MATCH_RESULT", "HOME")] == (1.3, 1.29)
    assert odds[("pinnacle", "MATCH_RESULT", "AWAY")] == (9.07, 9.75)
    assert odds[("market_average", "TOTAL_GOALS", "OVER")] == (1.35, 1.36)
    assert all(price is None or price > 1.0 for pair in odds.values() for price in pair)


def test_second_run_reuses_mappings_and_writes_nothing_new(
    db_session: Session, odds_provider: DataProvider
) -> None:
    _normalize(db_session, odds_provider)
    count = db_session.scalar(select(func.count()).select_from(HistoricalOdds))

    again = _normalize(db_session, odds_provider, CSV + b"\n")

    assert again.teams_mapped == 0
    assert again.matched == 380
    assert db_session.scalar(select(func.count()).select_from(HistoricalOdds)) == count


def test_unknown_team_is_left_unmatched_not_guessed(
    db_session: Session, odds_provider: DataProvider
) -> None:
    lines = CSV.decode("utf-8-sig").splitlines()
    lines[1] = lines[1].replace("Liverpool,Bournemouth", "Atlantis FC,Bournemouth")

    stats = _normalize(db_session, odds_provider, "\n".join(lines).encode())

    assert stats.matched == 379
    assert stats.unmatched == 1
    assert "Atlantis FC" in stats.unresolved_names
    assert stats.teams_mapped == 20


def _csv_fetcher() -> HttpFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mmz4281/2526/E0.csv":
            return httpx.Response(200, content=CSV)
        return httpx.Response(404)

    return HttpFetcher(
        httpx.Client(transport=httpx.MockTransport(handler)),
        RateLimiter(1000, burst=1000),
        FetchPolicy(expect_json=False),
    )


def test_season_job_fetches_normalizes_and_skips_unchanged(
    db_session: Session, odds_provider: DataProvider
) -> None:
    fetcher = _csv_fetcher()

    first = ingest_season(db_session, fetcher, "EPL", 2025)
    second = ingest_season(db_session, fetcher, "EPL", 2025)

    assert first["normalized"] is True
    assert first["matched"] == 380
    assert second == {"payload_changed": False, "normalized": False}


def test_unsupported_competition_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError, match="no football-data division"):
        enqueue_season(db_session, "RPL", 2025)


def test_backfill_command_queues_football_data_seasons(
    committed: sessionmaker[Session], worker_settings: None
) -> None:
    argv = ["backfill", "football-data", "--seasons", "2024-2025", "--leagues", "EPL,RFPL"]

    assert cli_main(argv) == 0

    with committed() as session:
        jobs = session.execute(
            text("SELECT count(*) FROM procrastinate_jobs WHERE task_name = :t"),
            {"t": SEASON_TASK},
        ).scalar_one()
    assert jobs == 2  # RFPL has no football-data division
