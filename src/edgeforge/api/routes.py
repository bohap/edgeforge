"""Read-only football endpoints behind the web app."""

import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from numpy.typing import NDArray
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.schemas import (
    ComparisonOut,
    CompetitionOut,
    EstimateOut,
    FixtureOut,
    FormWindowOut,
    MarketSideOut,
    MeetingOut,
    PolymarketOut,
    TeamMatchOut,
    TeamOut,
    TeamSideOut,
)
from edgeforge.catalog.models import Competition
from edgeforge.catalog.reference import competition_by_code, enabled_competitions
from edgeforge.compare.form import TeamMatch, Venue
from edgeforge.compare.service import FormWindow, compare_match, fit_ratings, next_meeting
from edgeforge.compare.value import priced_sides
from edgeforge.features.gateway import upcoming_fixtures
from edgeforge.football.teams import competition_teams, team_names
from edgeforge.marketdata.quotes import match_quotes
from edgeforge.models.football_goals.model import GoalRatings
from edgeforge.providers.polymarket.client import (
    MORE_MARKETS_SUFFIX,
    event_page_url,
)
from edgeforge.providers.polymarket.client import PROVIDER_CODE as POLYMARKET

router = APIRouter(prefix="/api")

TEAM_HISTORY = timedelta(days=400)
MAX_WINDOW = 50


def get_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class RatingsCache:
    """Fitted goal models per competition and hour, so page loads do not refit."""

    def __init__(self, size: int = 16) -> None:
        self._size = size
        self._items: OrderedDict[tuple[uuid.UUID, datetime], GoalRatings | None] = OrderedDict()
        self._lock = threading.Lock()

    def get(
        self, session: Session, competition_id: uuid.UUID, as_of: datetime
    ) -> GoalRatings | None:
        key = (competition_id, as_of)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        ratings = fit_ratings(session, competition_id, as_of)
        with self._lock:
            self._items[key] = ratings
            while len(self._items) > self._size:
                self._items.popitem(last=False)
        return ratings


def _competition(session: Session, code: str) -> Competition:
    competition = competition_by_code(session, code)
    if competition is None:
        raise HTTPException(404, f"unknown competition {code!r}")
    return competition


def _as_of(value: datetime | None) -> datetime:
    """Default: the start of the current hour, so repeated requests share one model fit."""
    if value is None:
        return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _team(team_id: uuid.UUID, names: dict[uuid.UUID, str]) -> TeamOut:
    return TeamOut(id=team_id, name=names.get(team_id, "unknown"))


@router.get("/competitions")
def competitions(session: SessionDep) -> list[CompetitionOut]:
    return [CompetitionOut.model_validate(c) for c in enabled_competitions(session)]


@router.get("/competitions/{code}/fixtures")
def fixtures(
    session: SessionDep,
    code: str,
    days: Annotated[int, Query(ge=1, le=60)] = 7,
    as_of: datetime | None = None,
) -> list[FixtureOut]:
    competition = _competition(session, code)
    start = _as_of(as_of)
    rows = upcoming_fixtures(
        session, start, start + timedelta(days=days), competition_id=competition.id
    )
    names = team_names(session, {t for f in rows for t in (f.home_team_id, f.away_team_id)})
    return [
        FixtureOut(
            match_id=f.match_id,
            kickoff_at=f.kickoff_at,
            home=_team(f.home_team_id, names),
            away=_team(f.away_team_id, names),
        )
        for f in rows
    ]


@router.get("/competitions/{code}/teams")
def teams(session: SessionDep, code: str) -> list[TeamOut]:
    competition = _competition(session, code)
    since = datetime.now(UTC) - TEAM_HISTORY
    return [
        TeamOut(id=team_id, name=name)
        for team_id, name in competition_teams(session, competition.id, since).items()
    ]


@router.get("/competitions/{code}/compare")
def compare(
    request: Request,
    session: SessionDep,
    code: str,
    home: uuid.UUID,
    away: uuid.UUID,
    last: Annotated[list[int], Query()] = [5, 10],  # noqa: B006 - FastAPI copies defaults
    as_of: datetime | None = None,
) -> ComparisonOut:
    if home == away:
        raise HTTPException(422, "home and away must be different teams")
    if not last or min(last) < 1 or max(last) > MAX_WINDOW:
        raise HTTPException(422, f"last must be between 1 and {MAX_WINDOW}")
    competition = _competition(session, code)
    names = team_names(session, [home, away])
    for team_id in (home, away):
        if team_id not in names:
            raise HTTPException(404, f"unknown team {team_id}")

    moment = _as_of(as_of)
    cache: RatingsCache = request.app.state.ratings_cache
    ratings = cache.get(session, competition.id, moment)
    comparison = compare_match(
        session, home, away, moment, windows=sorted(set(last)), ratings=ratings
    )
    opponents = {m.opponent_id for m in comparison.home_recent + comparison.away_recent}
    names |= team_names(session, opponents - names.keys())
    fixture = next_meeting(session, competition.id, home, away, moment)
    # Prices are read at the exact time asked (now by default), not the hour the model uses.
    prices_at = datetime.now(UTC) if as_of is None else moment
    polymarket = None
    if fixture is not None and comparison.estimate is not None and ratings is not None:
        polymarket = _polymarket(
            session, fixture.match_id, ratings.score_matrix(home, away), prices_at
        )

    return ComparisonOut(
        as_of=moment,
        competition=CompetitionOut.model_validate(competition),
        home=TeamSideOut(
            team=_team(home, names),
            last_played=comparison.home_last_played,
            form=[_window(w) for w in comparison.home_form],
            recent=[_team_match(m, names) for m in comparison.home_recent],
        ),
        away=TeamSideOut(
            team=_team(away, names),
            last_played=comparison.away_last_played,
            form=[_window(w) for w in comparison.away_form],
            recent=[_team_match(m, names) for m in comparison.away_recent],
        ),
        head_to_head=[_meeting(m, names) for m in comparison.head_to_head],
        estimate=(EstimateOut.model_validate(comparison.estimate) if comparison.estimate else None),
        kickoff_at=fixture.kickoff_at if fixture else None,
        polymarket=polymarket,
    )


def _polymarket(
    session: Session, match_id: uuid.UUID, matrix: NDArray[np.float64], as_of: datetime
) -> PolymarketOut | None:
    quotes = match_quotes(session, match_id, POLYMARKET, as_of)
    if not quotes:
        return None
    main = next(
        (q.event_slug for q in quotes if q.market_code == "MATCH_RESULT"),
        quotes[0].event_slug.removesuffix(MORE_MARKETS_SUFFIX),
    )
    return PolymarketOut(
        url=event_page_url(main),
        observed_at=max(q.observed_at for q in quotes),
        sides=[
            MarketSideOut(
                market_code=s.market_code,
                params=s.params,
                outcome=s.outcome,
                negated=s.negated,
                price=s.price,
                odds=s.odds,
                market_probability=s.market_probability,
                model_probability=s.model_probability,
                edge=s.edge,
                liquidity=s.liquidity,
                url=event_page_url(s.event_slug),
            )
            for s in priced_sides(matrix, quotes)
        ],
    )


def _window(window: FormWindow) -> FormWindowOut:
    return FormWindowOut.model_validate(window)


def _team_match(m: TeamMatch, names: dict[uuid.UUID, str]) -> TeamMatchOut:
    return TeamMatchOut(
        kickoff_at=m.kickoff_at,
        opponent=_team(m.opponent_id, names),
        venue=m.venue.value,
        goals_for=m.goals_for,
        goals_against=m.goals_against,
        xg_for=m.xg_for,
        xg_against=m.xg_against,
        result=m.result,
    )


def _meeting(m: TeamMatch, names: dict[uuid.UUID, str]) -> MeetingOut:
    """``m`` is from the home side of the requested match; show the real venue order."""
    team, opponent = _team(m.team_id, names), _team(m.opponent_id, names)
    if m.venue is Venue.HOME:
        return MeetingOut(
            kickoff_at=m.kickoff_at,
            home=team,
            away=opponent,
            home_goals=m.goals_for,
            away_goals=m.goals_against,
            home_xg=m.xg_for,
            away_xg=m.xg_against,
        )
    return MeetingOut(
        kickoff_at=m.kickoff_at,
        home=opponent,
        away=team,
        home_goals=m.goals_against,
        away_goals=m.goals_for,
        home_xg=m.xg_against,
        away_xg=m.xg_for,
    )
