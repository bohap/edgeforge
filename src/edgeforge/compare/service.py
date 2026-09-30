"""Build a match comparison from data known at ``as_of`` (via ``features.played_matches``)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from edgeforge.compare.form import FormSummary, TeamMatch, Venue, head_to_head, summarize
from edgeforge.compare.form import team_matches as team_matches_of
from edgeforge.features.gateway import played_matches
from edgeforge.markets.football import MARKET_TYPES, price
from edgeforge.models.football_goals.model import GoalModelConfig, GoalRatings, fit

MODEL_HISTORY = timedelta(days=3 * 365)
MIN_TRAINING_MATCHES = 50


@dataclass(frozen=True, slots=True)
class FormWindow:
    """One team's last ``last`` matches overall and at the venue it plays this match at."""

    last: int
    overall: FormSummary | None
    at_venue: FormSummary | None


@dataclass(frozen=True, slots=True)
class Estimate:
    """Estimated probabilities from the goal model for one match."""

    expected_home_goals: float
    expected_away_goals: float
    home_win: float
    draw: float
    away_win: float
    both_score: float
    over_2_5: float
    likely_score: tuple[int, int]
    likely_score_probability: float


@dataclass(frozen=True, slots=True)
class MatchComparison:
    as_of: datetime
    home_team_id: uuid.UUID
    away_team_id: uuid.UUID
    home_form: list[FormWindow]
    away_form: list[FormWindow]
    head_to_head: list[TeamMatch]
    estimate: Estimate | None
    home_last_played: datetime | None = None
    away_last_played: datetime | None = None


def fit_ratings(
    session: Session,
    competition_id: uuid.UUID,
    as_of: datetime,
    config: GoalModelConfig | None = None,
) -> GoalRatings | None:
    """Goal model for one competition, or ``None`` with too little history."""
    training = played_matches(
        session, as_of, competition_id=competition_id, since=as_of - MODEL_HISTORY
    )
    if len(training) < MIN_TRAINING_MATCHES:
        return None
    return fit(training, as_of, config)


def compare_match(
    session: Session,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    as_of: datetime,
    *,
    windows: Sequence[int] = (5, 10),
    ratings: GoalRatings | None = None,
) -> MatchComparison:
    """Form over each window (all competitions), head-to-head and, when ``ratings`` rate
    both teams, estimated probabilities."""
    home_matches = played_matches(session, as_of, team_id=home_team_id)
    away_matches = played_matches(session, as_of, team_id=away_team_id)
    home_side = team_matches_of(home_matches, home_team_id)
    away_side = team_matches_of(away_matches, away_team_id)
    return MatchComparison(
        as_of=as_of,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_form=form_windows(home_side, windows, Venue.HOME),
        away_form=form_windows(away_side, windows, Venue.AWAY),
        head_to_head=head_to_head(home_matches, home_team_id, away_team_id),
        estimate=estimate(ratings, home_team_id, away_team_id) if ratings else None,
        home_last_played=home_side[0].kickoff_at if home_side else None,
        away_last_played=away_side[0].kickoff_at if away_side else None,
    )


def estimate(ratings: GoalRatings, home: uuid.UUID, away: uuid.UUID) -> Estimate | None:
    """``None`` when either team has no matches in the model's training data: the model
    would silently rate it as league average."""
    if home not in ratings.attack or away not in ratings.attack:
        return None
    lambda_home, lambda_away = ratings.expected_goals(home, away)
    matrix = ratings.score_matrix(home, away)
    result = price(matrix, MARKET_TYPES["MATCH_RESULT"])
    btts = price(matrix, MARKET_TYPES["BTTS"])
    totals = price(matrix, MARKET_TYPES["TOTAL_GOALS"], line=2.5)
    likely = np.unravel_index(int(np.argmax(matrix)), matrix.shape)
    return Estimate(
        expected_home_goals=lambda_home,
        expected_away_goals=lambda_away,
        home_win=result["HOME"].win,
        draw=result["DRAW"].win,
        away_win=result["AWAY"].win,
        both_score=btts["YES"].win,
        over_2_5=totals["OVER"].win,
        likely_score=(int(likely[0]), int(likely[1])),
        likely_score_probability=float(matrix[likely]),
    )


def form_windows(
    matches: Sequence[TeamMatch], windows: Sequence[int], venue: Venue
) -> list[FormWindow]:
    """Summaries of the newest ``n`` matches (newest first) overall and at ``venue``."""
    at_venue = [m for m in matches if m.venue is venue]
    return [FormWindow(n, summarize(matches[:n]), summarize(at_venue[:n])) for n in windows]
