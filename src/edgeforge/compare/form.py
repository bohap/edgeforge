"""Recent-form summaries computed from played matches, from one team's point of view."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from edgeforge.features.gateway import PlayedMatch


class Venue(StrEnum):
    HOME = "home"
    AWAY = "away"


@dataclass(frozen=True, slots=True)
class TeamMatch:
    """A played match seen from one team's side."""

    kickoff_at: datetime
    team_id: uuid.UUID
    opponent_id: uuid.UUID
    venue: Venue
    goals_for: int
    goals_against: int
    xg_for: float | None
    xg_against: float | None

    @property
    def result(self) -> str:
        if self.goals_for > self.goals_against:
            return "W"
        if self.goals_for < self.goals_against:
            return "L"
        return "D"

    @property
    def points(self) -> int:
        return {"W": 3, "D": 1, "L": 0}[self.result]


def team_matches(
    matches: Sequence[PlayedMatch], team_id: uuid.UUID, *, venue: Venue | None = None
) -> list[TeamMatch]:
    """The team's matches, newest first, optionally only at home or only away."""
    out = []
    for m in matches:
        if m.home_team_id == team_id and venue in (None, Venue.HOME):
            out.append(_side(m, Venue.HOME))
        elif m.away_team_id == team_id and venue in (None, Venue.AWAY):
            out.append(_side(m, Venue.AWAY))
    out.sort(key=lambda t: t.kickoff_at, reverse=True)
    return out


def _side(m: PlayedMatch, venue: Venue) -> TeamMatch:
    if venue is Venue.HOME:
        return TeamMatch(
            kickoff_at=m.kickoff_at,
            team_id=m.home_team_id,
            opponent_id=m.away_team_id,
            venue=venue,
            goals_for=m.home_goals,
            goals_against=m.away_goals,
            xg_for=m.home_xg,
            xg_against=m.away_xg,
        )
    return TeamMatch(
        kickoff_at=m.kickoff_at,
        team_id=m.away_team_id,
        opponent_id=m.home_team_id,
        venue=venue,
        goals_for=m.away_goals,
        goals_against=m.home_goals,
        xg_for=m.away_xg,
        xg_against=m.home_xg,
    )


@dataclass(frozen=True, slots=True)
class FormSummary:
    """Averages over a run of matches. xG averages cover only matches with xG
    (``xg_matches`` of them) and are ``None`` when there are none."""

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


def summarize(matches: Sequence[TeamMatch]) -> FormSummary | None:
    """Summary of the given matches (newest first); ``None`` for an empty run."""
    n = len(matches)
    if n == 0:
        return None
    with_xg = [m for m in matches if m.xg_for is not None and m.xg_against is not None]
    results = "".join(m.result for m in matches)
    return FormSummary(
        matches=n,
        results=results,
        wins=results.count("W"),
        draws=results.count("D"),
        losses=results.count("L"),
        points_per_game=sum(m.points for m in matches) / n,
        goals_for=sum(m.goals_for for m in matches) / n,
        goals_against=sum(m.goals_against for m in matches) / n,
        xg_for=_mean([m.xg_for for m in with_xg]),
        xg_against=_mean([m.xg_against for m in with_xg]),
        xg_matches=len(with_xg),
        both_scored=sum(1 for m in matches if m.goals_for > 0 and m.goals_against > 0),
        over_2_5=sum(1 for m in matches if m.goals_for + m.goals_against > 2),
    )


def head_to_head(
    matches: Sequence[PlayedMatch], team_id: uuid.UUID, opponent_id: uuid.UUID
) -> list[TeamMatch]:
    """Meetings between the two teams at either venue, newest first, from ``team_id``'s side."""
    return [m for m in team_matches(matches, team_id) if m.opponent_id == opponent_id]


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None
