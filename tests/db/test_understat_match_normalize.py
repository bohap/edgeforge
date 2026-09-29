from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import DataProvider, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.football.models import Match, MatchResult, Player, PlayerMatchStats, Shot
from edgeforge.providers.understat.normalize import (
    RESULT_AVAILABILITY_LAG,
    normalize_league_payload,
)
from edgeforge.providers.understat.normalize_match import (
    MatchNormalizeStats,
    UnknownEntityError,
    normalize_match_payload,
)
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
FETCHED = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _record(
    session: Session, provider: DataProvider, resource: str, key: str, body: bytes, at: datetime
) -> RawPayload:
    result = record_payload(
        session,
        PostgresBlobStore(session),
        provider_id=provider.id,
        resource=resource,
        key=key,
        url=f"https://understat.com/{resource}/{key}",
        http_status=200,
        body=body,
        fetched_at=at,
    )
    return session.get_one(RawPayload, result.payload_id)


def _normalize_match(
    session: Session, provider: DataProvider, at: datetime = FETCHED
) -> MatchNormalizeStats:
    payload = _record(
        session, provider, "match", "28778", (FIXTURES / "match_28778.json").read_bytes(), at
    )
    return normalize_match_payload(session, PostgresBlobStore(session), payload)


@pytest.fixture
def understat(db_session: Session) -> DataProvider:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)
    league = _record(
        db_session,
        provider,
        "league",
        "EPL/2025",
        (FIXTURES / "league_EPL_2025.json").read_bytes(),
        FETCHED,
    )
    normalize_league_payload(db_session, PostgresBlobStore(db_session), league)
    return provider


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_match_payload_creates_players_appearances_and_shots(
    db_session: Session, understat: DataProvider
) -> None:
    stats = _normalize_match(db_session, understat)

    assert stats.as_dict() == {"players_created": 31, "appearances": 31, "shots": 29}
    assert _count(db_session, Player) == 31
    assert _count(db_session, PlayerMatchStats) == 31
    assert _count(db_session, Shot) == 29


def test_appearances_match_the_result(db_session: Session, understat: DataProvider) -> None:
    _normalize_match(db_session, understat)

    match = db_session.scalars(select(Match).join(Shot, Shot.match_id == Match.id).limit(1)).one()
    result = db_session.get_one(MatchResult, match.id)
    rows = db_session.scalars(
        select(PlayerMatchStats).where(PlayerMatchStats.match_id == match.id)
    ).all()

    def goals_for(team_id: object, opponent_id: object) -> int:
        scored = sum(r.goals for r in rows if r.team_id == team_id)
        own_goals_by_opponent = sum(r.own_goals for r in rows if r.team_id == opponent_id)
        return scored + own_goals_by_opponent

    assert goals_for(match.home_team_id, match.away_team_id) == result.home_goals
    assert goals_for(match.away_team_id, match.home_team_id) == result.away_goals
    assert sum(r.started for r in rows) == 22
    assert all(r.minutes > 0 for r in rows)


def test_shots_carry_team_flags_and_availability(
    db_session: Session, understat: DataProvider
) -> None:
    _normalize_match(db_session, understat)

    match = db_session.scalars(select(Match).join(Shot, Shot.match_id == Match.id).limit(1)).one()
    shots = db_session.scalars(select(Shot).where(Shot.match_id == match.id)).all()
    home = [s for s in shots if s.team_id == match.home_team_id]

    assert len(home) == 19
    assert sum(s.xg for s in home) == pytest.approx(2.33007, abs=1e-4)
    assert all(s.is_goal == (s.result == "Goal") for s in shots)
    assert {s.available_at for s in shots} == {match.kickoff_at + RESULT_AVAILABILITY_LAG}


def test_normalizing_again_is_idempotent(db_session: Session, understat: DataProvider) -> None:
    _normalize_match(db_session, understat)
    first_shot = db_session.scalars(select(Shot).order_by(Shot.external_id).limit(1)).one()
    observed = first_shot.observed_at

    stats = _normalize_match(db_session, understat, FETCHED + timedelta(days=1))

    db_session.refresh(first_shot)
    assert stats.players_created == 0
    assert _count(db_session, Player) == 31
    assert _count(db_session, Shot) == 29
    assert first_shot.observed_at == observed


def test_match_payload_before_its_league_is_rejected(db_session: Session) -> None:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)

    with pytest.raises(UnknownEntityError, match="normalize its league payload first"):
        _normalize_match(db_session, provider)

    assert _count(db_session, Player) == 0
