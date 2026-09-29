import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import DataProvider, ProviderKind, Season
from edgeforge.catalog.reference import ensure_provider
from edgeforge.football.models import (
    Match,
    MatchResult,
    MatchStatus,
    MatchTeamStats,
    Team,
    TeamSeason,
)
from edgeforge.providers.understat.normalize import (
    RESULT_AVAILABILITY_LAG,
    LeagueNormalizeStats,
    normalize_league_payload,
)
from edgeforge.providers.understat.schemas import PARSER_VERSION
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
FETCHED = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
def understat(db_session: Session) -> DataProvider:
    return ensure_provider(db_session, "understat", ProviderKind.STATS)


def _ingest(
    session: Session,
    provider: DataProvider,
    key: str,
    body: bytes,
    fetched_at: datetime = FETCHED,
) -> LeagueNormalizeStats:
    store = PostgresBlobStore(session)
    result = record_payload(
        session,
        store,
        provider_id=provider.id,
        resource="league",
        key=key,
        url=f"https://understat.com/getLeagueData/{key}",
        http_status=200,
        body=body,
        fetched_at=fetched_at,
    )
    payload = session.get_one(RawPayload, result.payload_id)
    return normalize_league_payload(session, store, payload)


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _match_by_teams(session: Session, home: str, away: str, season_label: str) -> Match:
    home_team = session.scalars(select(Team).where(Team.name == home)).one()
    away_team = session.scalars(select(Team).where(Team.name == away)).one()
    return session.scalars(
        select(Match)
        .join(Season, Season.id == Match.season_id)
        .where(
            Match.home_team_id == home_team.id,
            Match.away_team_id == away_team.id,
            Season.label == season_label,
        )
    ).one()


def test_completed_season_is_fully_normalized(db_session: Session, understat: DataProvider) -> None:
    stats = _ingest(
        db_session, understat, "EPL/2025", (FIXTURES / "league_EPL_2025.json").read_bytes()
    )

    season = db_session.scalars(select(Season)).one()
    assert stats.as_dict() == {
        "teams_created": 20,
        "matches_created": 380,
        "matches_updated": 0,
        "results_written": 380,
    }
    assert (season.label, season.start_date, season.end_date) == (
        "2025/26",
        date(2025, 8, 15),
        date(2026, 5, 24),
    )
    assert _count(db_session, TeamSeason) == 20
    assert _count(db_session, MatchResult) == 380
    assert _count(db_session, MatchTeamStats) == 760
    assert db_session.scalars(select(RawPayload)).one().parser_version == PARSER_VERSION


def test_result_and_team_stats_carry_values_and_provenance(
    db_session: Session, understat: DataProvider
) -> None:
    _ingest(db_session, understat, "EPL/2025", (FIXTURES / "league_EPL_2025.json").read_bytes())

    match = _match_by_teams(db_session, "Liverpool", "Bournemouth", "2025/26")
    result = db_session.get_one(MatchResult, match.id)
    home = db_session.scalars(
        select(MatchTeamStats).where(MatchTeamStats.match_id == match.id, MatchTeamStats.is_home)
    ).one()

    assert match.status is MatchStatus.FINISHED
    assert match.kickoff_at == datetime(2025, 8, 15, 19, 0, tzinfo=UTC)
    assert (result.home_goals, result.away_goals) == (4, 2)
    assert home.goals == 4
    assert home.xg == pytest.approx(2.33007)
    assert home.npxg is not None
    assert home.ppda_passes is not None
    assert home.deep_completions is not None
    # Fetched long after the match: availability is capped at kickoff + lag.
    assert result.available_at == match.kickoff_at + RESULT_AVAILABILITY_LAG
    assert result.observed_at == FETCHED
    assert result.provider_id == understat.id


def test_normalizing_twice_changes_nothing(db_session: Session, understat: DataProvider) -> None:
    body = (FIXTURES / "league_EPL_2025.json").read_bytes()
    _ingest(db_session, understat, "EPL/2025", body)

    second = _ingest(db_session, understat, "EPL/2025", body, FETCHED + timedelta(days=1))

    assert second.as_dict() == {
        "teams_created": 0,
        "matches_created": 0,
        "matches_updated": 0,
        "results_written": 380,
    }
    assert _count(db_session, Match) == 380
    assert _count(db_session, MatchTeamStats) == 760
    assert _count(db_session, Team) == 20


def test_teams_are_shared_across_seasons_and_new_ones_added(
    db_session: Session, understat: DataProvider
) -> None:
    _ingest(db_session, understat, "EPL/2025", (FIXTURES / "league_EPL_2025.json").read_bytes())
    stats = _ingest(
        db_session, understat, "EPL/2026", (FIXTURES / "league_EPL_2026.json").read_bytes()
    )

    arsenal = db_session.scalars(select(Team).where(Team.name == "Arsenal")).all()
    seasons = db_session.scalars(
        select(Season.label)
        .join(TeamSeason, TeamSeason.season_id == Season.id)
        .where(TeamSeason.team_id == arsenal[0].id)
        .order_by(Season.label)
    ).all()
    assert len(arsenal) == 1
    assert seasons == ["2025/26", "2026/27"]
    assert stats.teams_created == 3  # promoted teams
    assert db_session.scalars(select(Team).where(Team.name == "Coventry")).one()


def test_future_fixtures_are_scheduled_without_results(
    db_session: Session, understat: DataProvider
) -> None:
    stats = _ingest(
        db_session, understat, "EPL/2026", (FIXTURES / "league_EPL_2026.json").read_bytes()
    )

    scheduled = db_session.scalar(
        select(func.count()).select_from(Match).where(Match.status == MatchStatus.SCHEDULED)
    )
    assert scheduled == 330
    assert stats.results_written == 50
    assert _count(db_session, MatchResult) == 50


def test_rescheduled_fixture_updates_kickoff(db_session: Session, understat: DataProvider) -> None:
    raw = json.loads((FIXTURES / "league_EPL_2026.json").read_bytes())
    _ingest(db_session, understat, "EPL/2026", json.dumps(raw).encode())
    fixture = next(f for f in raw["dates"] if not f["isResult"])
    fixture["datetime"] = "2026-12-30 20:00:00"

    stats = _ingest(
        db_session, understat, "EPL/2026", json.dumps(raw).encode(), FETCHED + timedelta(hours=1)
    )

    match = _match_by_teams(db_session, fixture["h"]["title"], fixture["a"]["title"], "2026/27")
    assert stats.matches_updated == 1
    assert match.kickoff_at == datetime(2026, 12, 30, 20, 0, tzinfo=UTC)
    assert match.observed_at == FETCHED + timedelta(hours=1)


def test_revised_xg_updates_stats_and_their_availability(
    db_session: Session, understat: DataProvider
) -> None:
    raw = json.loads((FIXTURES / "league_EPL_2025.json").read_bytes())
    _ingest(db_session, understat, "EPL/2025", json.dumps(raw).encode())
    raw["dates"][0]["xG"]["h"] = "2.5"
    revised_at = FETCHED + timedelta(days=2)

    _ingest(db_session, understat, "EPL/2025", json.dumps(raw).encode(), revised_at)

    match = _match_by_teams(db_session, "Liverpool", "Bournemouth", "2025/26")
    home = db_session.scalars(
        select(MatchTeamStats).where(MatchTeamStats.match_id == match.id, MatchTeamStats.is_home)
    ).one()
    away = db_session.scalars(
        select(MatchTeamStats).where(
            MatchTeamStats.match_id == match.id, MatchTeamStats.is_home.is_(False)
        )
    ).one()
    assert home.xg == pytest.approx(2.5)
    assert home.observed_at == revised_at
    assert away.observed_at == FETCHED  # unchanged row keeps its original provenance


def test_rejects_non_league_payload(db_session: Session, understat: DataProvider) -> None:
    store = PostgresBlobStore(db_session)
    result = record_payload(
        db_session,
        store,
        provider_id=understat.id,
        resource="match",
        key="1",
        url="u",
        http_status=200,
        body=b"{}",
        fetched_at=FETCHED,
    )

    with pytest.raises(ValueError, match="'match' payload"):
        normalize_league_payload(
            db_session, store, db_session.get_one(RawPayload, result.payload_id)
        )
