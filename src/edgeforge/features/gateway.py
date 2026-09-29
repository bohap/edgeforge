"""The single read path from normalized data to models.

Every query takes ``as_of`` and returns only what was knowable at that moment: matches that
kicked off before ``as_of`` whose result and statistics were available (``available_at``)
by then. A prediction made at ``as_of`` therefore cannot see later information, and a
backtest that replays ``as_of`` sees exactly what a live run would have seen.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from edgeforge.football.models import Match, MatchResult, MatchTeamStats


@dataclass(frozen=True, slots=True)
class PlayedMatch:
    """A finished match as known at ``as_of``. Statistics are ``None`` when unavailable."""

    match_id: uuid.UUID
    competition_id: uuid.UUID
    season_id: uuid.UUID
    kickoff_at: datetime
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    home_goals: int
    away_goals: int
    home_xg: float | None
    away_xg: float | None
    home_npxg: float | None
    away_npxg: float | None


def played_matches(
    session: Session,
    as_of: datetime,
    *,
    competition_id: uuid.UUID | None = None,
    since: datetime | None = None,
    team_id: uuid.UUID | None = None,
) -> list[PlayedMatch]:
    """Finished matches known at ``as_of``, oldest first.

    A match is included only if it kicked off before ``as_of`` and its result was available
    by ``as_of``. Team statistics that became available later are returned as ``None``
    rather than dropping the match.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    home = aliased(MatchTeamStats)
    away = aliased(MatchTeamStats)
    query = (
        select(
            Match.id.label("match_id"),
            Match.competition_id,
            Match.season_id,
            Match.kickoff_at,
            Match.home_team_id,
            Match.away_team_id,
            MatchResult.home_goals,
            MatchResult.away_goals,
            home.xg.label("home_xg"),
            away.xg.label("away_xg"),
            home.npxg.label("home_npxg"),
            away.npxg.label("away_npxg"),
        )
        .join(MatchResult, MatchResult.match_id == Match.id)
        .outerjoin(
            home,
            and_(
                home.match_id == Match.id,
                home.team_id == Match.home_team_id,
                home.available_at <= as_of,
            ),
        )
        .outerjoin(
            away,
            and_(
                away.match_id == Match.id,
                away.team_id == Match.away_team_id,
                away.available_at <= as_of,
            ),
        )
        .where(Match.kickoff_at < as_of, MatchResult.available_at <= as_of)
        .order_by(Match.kickoff_at, Match.id)
    )
    if competition_id is not None:
        query = query.where(Match.competition_id == competition_id)
    if since is not None:
        query = query.where(Match.kickoff_at >= since)
    if team_id is not None:
        query = query.where((Match.home_team_id == team_id) | (Match.away_team_id == team_id))

    return [PlayedMatch(**row) for row in session.execute(query).mappings()]


@dataclass(frozen=True, slots=True)
class Fixture:
    match_id: uuid.UUID
    competition_id: uuid.UUID
    season_id: uuid.UUID
    kickoff_at: datetime
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID


def upcoming_fixtures(
    session: Session,
    as_of: datetime,
    until: datetime,
    *,
    competition_id: uuid.UUID | None = None,
) -> list[Fixture]:
    """Matches scheduled to kick off in ``[as_of, until)``.

    Uses the current schedule. Knowing that a fixture exists carries no result information,
    so this is not a leakage risk; results and statistics always go through
    ``played_matches``.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    query = (
        select(
            Match.id,
            Match.competition_id,
            Match.season_id,
            Match.kickoff_at,
            Match.home_team_id,
            Match.away_team_id,
        )
        .where(
            Match.kickoff_at >= as_of,
            Match.kickoff_at < until,
        )
        .order_by(Match.kickoff_at, Match.id)
    )
    if competition_id is not None:
        query = query.where(Match.competition_id == competition_id)
    return [Fixture(*row) for row in session.execute(query)]
