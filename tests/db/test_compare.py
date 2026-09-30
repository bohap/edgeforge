import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import Competition, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.cli import parse_windows
from edgeforge.compare.report import render
from edgeforge.compare.service import compare_match, fit_ratings
from edgeforge.football.teams import TeamLookupError, find_team, team_names
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
AS_OF = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture
def season(db_session: Session) -> Session:
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
    return db_session


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Arsenal", "Arsenal"),
        ("arsenal", "Arsenal"),
        ("man city", "Manchester City"),
        ("Man Utd", "Manchester United"),
        ("wolves", "Wolverhampton Wanderers"),
        ("forest", "Nottingham Forest"),
    ],
)
def test_find_team(season: Session, query: str, expected: str) -> None:
    team = find_team(season, query)
    assert team_names(season, [team]) == {team: expected}


def test_find_team_reports_ambiguous_and_unknown_names(season: Session) -> None:
    with pytest.raises(TeamLookupError, match="Manchester United, Newcastle United"):
        find_team(season, "united")
    with pytest.raises(TeamLookupError, match="no team matches"):
        find_team(season, "Real Madrid")


def test_comparison_uses_only_matches_before_as_of(season: Session) -> None:
    competition = season.scalars(select(Competition.id)).one()
    arsenal, chelsea = find_team(season, "Arsenal"), find_team(season, "Chelsea")
    ratings = fit_ratings(season, competition, AS_OF)

    comparison = compare_match(season, arsenal, chelsea, AS_OF, windows=(5, 10), ratings=ratings)

    assert comparison.home_last_played is not None
    assert comparison.home_last_played < AS_OF
    assert comparison.away_last_played is not None
    assert comparison.away_last_played < AS_OF
    assert [w.last for w in comparison.home_form] == [5, 10]
    ten = comparison.home_form[1].overall
    assert ten is not None
    assert ten.matches == 10
    assert ten.xg_matches == 10
    assert all(m.kickoff_at < AS_OF for m in comparison.head_to_head)
    assert comparison.estimate is not None

    text = render(comparison, team_names(season, [arsenal, chelsea]))
    assert text.startswith("Arsenal vs Chelsea")
    assert "Estimated probabilities" in text


def test_no_estimate_before_the_model_has_enough_matches(season: Session) -> None:
    competition = season.scalars(select(Competition.id)).one()
    assert fit_ratings(season, competition, datetime(2025, 8, 20, tzinfo=UTC)) is None


def test_parse_windows() -> None:
    assert parse_windows("5,10,20") == [5, 10, 20]
    with pytest.raises(argparse.ArgumentTypeError):
        parse_windows("0,5")
