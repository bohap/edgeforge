from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from edgeforge.catalog.models import ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.features.gateway import played_matches, upcoming_fixtures
from edgeforge.football.models import Match, MatchResult, MatchTeamStats, Team
from edgeforge.providers.understat.normalize import (
    RESULT_AVAILABILITY_LAG,
    normalize_league_payload,
)
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
FETCHED = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
# Saturday 1 November 2025, 12:00 UTC: mid-season, before that day's matches.
AS_OF = datetime(2025, 11, 1, 12, 0, tzinfo=UTC)


def _load(session: Session, key: str, name: str) -> None:
    provider = ensure_provider(session, "understat", ProviderKind.STATS)
    store = PostgresBlobStore(session)
    result = record_payload(
        session,
        store,
        provider_id=provider.id,
        resource="league",
        key=key,
        url=f"https://understat.com/getLeagueData/{key}",
        http_status=200,
        body=(FIXTURES / name).read_bytes(),
        fetched_at=FETCHED,
    )
    normalize_league_payload(session, store, session.get_one(RawPayload, result.payload_id))


@pytest.fixture
def season(db_session: Session) -> Session:
    _load(db_session, "EPL/2025", "league_EPL_2025.json")
    return db_session


def test_only_matches_with_public_results_are_returned(season: Session) -> None:
    rows = played_matches(season, AS_OF)

    assert rows
    assert all(r.kickoff_at + RESULT_AVAILABILITY_LAG <= AS_OF for r in rows)
    kickoffs = [r.kickoff_at for r in rows]
    assert kickoffs == sorted(kickoffs)
    expected = season.scalars(
        select(Match.id).where(Match.kickoff_at + RESULT_AVAILABILITY_LAG <= AS_OF)
    ).all()
    assert {r.match_id for r in rows} == set(expected)


def test_match_that_just_finished_is_not_yet_visible(season: Session) -> None:
    kickoff = season.scalars(
        select(Match.kickoff_at).where(Match.kickoff_at < AS_OF).order_by(Match.kickoff_at.desc())
    ).first()
    assert kickoff is not None
    just_after = kickoff + timedelta(hours=2)

    visible = {r.kickoff_at for r in played_matches(season, just_after)}
    later = {r.kickoff_at for r in played_matches(season, kickoff + RESULT_AVAILABILITY_LAG)}

    assert kickoff not in visible
    assert kickoff in later


def test_changing_later_data_cannot_change_the_answer(season: Session) -> None:
    before = played_matches(season, AS_OF)
    later_matches = select(Match.id).where(Match.kickoff_at >= AS_OF - RESULT_AVAILABILITY_LAG)

    season.execute(
        update(MatchResult)
        .where(MatchResult.match_id.in_(later_matches))
        .values(home_goals=9, away_goals=9)
    )
    season.execute(
        update(MatchTeamStats)
        .where(MatchTeamStats.match_id.in_(later_matches))
        .values(xg=9.9, npxg=9.9)
    )
    season.expire_all()

    assert played_matches(season, AS_OF) == before


def test_statistics_published_after_as_of_are_hidden_but_result_kept(season: Session) -> None:
    target = played_matches(season, AS_OF)[-1]
    season.execute(
        update(MatchTeamStats)
        .where(MatchTeamStats.match_id == target.match_id)
        .values(available_at=AS_OF + timedelta(days=1))
    )
    season.expire_all()

    row = next(r for r in played_matches(season, AS_OF) if r.match_id == target.match_id)

    assert (row.home_goals, row.away_goals) == (target.home_goals, target.away_goals)
    assert (row.home_xg, row.away_xg, row.home_npxg, row.away_npxg) == (None, None, None, None)


def test_filters_by_team_and_start(season: Session) -> None:
    arsenal = season.scalars(select(Team.id).where(Team.name == "Arsenal")).one()
    since = datetime(2025, 10, 1, tzinfo=UTC)

    rows = played_matches(season, AS_OF, team_id=arsenal, since=since)

    assert rows
    assert all(arsenal in (r.home_team_id, r.away_team_id) for r in rows)
    assert all(r.kickoff_at >= since for r in rows)
    assert all(r.home_xg is not None for r in rows)


def test_upcoming_fixtures_window(db_session: Session) -> None:
    _load(db_session, "EPL/2026", "league_EPL_2026.json")
    start = datetime(2026, 10, 10, tzinfo=UTC)

    fixtures = upcoming_fixtures(db_session, start, start + timedelta(days=4))

    assert fixtures
    assert all(start <= f.kickoff_at < start + timedelta(days=4) for f in fixtures)


def test_naive_as_of_is_rejected(season: Session) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        played_matches(season, datetime(2025, 11, 1))  # noqa: DTZ001
