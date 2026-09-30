"""JSON shapes returned by the HTTP API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class CompetitionOut(Model):
    code: str
    name: str
    country: str | None


class TeamOut(Model):
    id: uuid.UUID
    name: str


class FixtureOut(Model):
    match_id: uuid.UUID
    kickoff_at: datetime
    home: TeamOut
    away: TeamOut


class FormOut(Model):
    """Summary over a run of matches. xG averages are ``None`` when no match has xG."""

    matches: int
    results: str
    wins: int
    draws: int
    losses: int
    points_per_game: float
    goals_for: float
    goals_against: float
    xg_for: float | None
    xg_against: float | None
    xg_matches: int
    both_scored: int
    over_2_5: int


class FormWindowOut(Model):
    last: int
    overall: FormOut | None
    at_venue: FormOut | None


class TeamMatchOut(Model):
    """One match from a team's side."""

    kickoff_at: datetime
    opponent: TeamOut
    venue: str
    goals_for: int
    goals_against: int
    xg_for: float | None
    xg_against: float | None
    result: str


class MeetingOut(Model):
    """An earlier meeting, in its real home-away order."""

    kickoff_at: datetime
    home: TeamOut
    away: TeamOut
    home_goals: int
    away_goals: int
    home_xg: float | None
    away_xg: float | None


class EstimateOut(Model):
    """Estimated probabilities from the goal model."""

    expected_home_goals: float
    expected_away_goals: float
    home_win: float
    draw: float
    away_win: float
    both_score: float
    over_2_5: float
    likely_score: tuple[int, int]
    likely_score_probability: float


class TeamSideOut(Model):
    team: TeamOut
    last_played: datetime | None
    form: list[FormWindowOut]
    recent: list[TeamMatchOut]


class ComparisonOut(Model):
    as_of: datetime
    competition: CompetitionOut
    home: TeamSideOut
    away: TeamSideOut
    head_to_head: list[MeetingOut]
    estimate: EstimateOut | None
