"""Football market types, settled on the score after 90 minutes plus stoppage time.

Adding a market means adding one settlement function and registering it; pricing and grading
come for free. Whole-number goal lines can push (stake returned), reported as ``VOID``.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray


class Settlement(StrEnum):
    WIN = "win"
    LOSE = "lose"
    VOID = "void"


class Side(StrEnum):
    HOME = "home"
    AWAY = "away"


@dataclass(frozen=True, slots=True)
class FootballState:
    home_goals: int
    away_goals: int

    def goals(self, side: Side) -> int:
        return self.home_goals if side is Side.HOME else self.away_goals

    def margin(self, side: Side) -> int:
        return self.goals(side) - self.goals(Side.AWAY if side is Side.HOME else Side.HOME)


Settle = Callable[..., dict[str, Settlement]]


@dataclass(frozen=True, slots=True)
class MarketType:
    code: str
    outcomes: tuple[str, ...]
    params: tuple[str, ...]
    settle_fn: Settle
    description: str

    def settle(self, state: FootballState, **params: Any) -> dict[str, Settlement]:
        if set(params) != set(self.params):
            raise ValueError(f"{self.code} expects parameters {self.params}, got {tuple(params)}")
        return self.settle_fn(state, **params)


def _won(condition: bool) -> Settlement:
    return Settlement.WIN if condition else Settlement.LOSE


def _match_result(s: FootballState) -> dict[str, Settlement]:
    return {
        "HOME": _won(s.home_goals > s.away_goals),
        "DRAW": _won(s.home_goals == s.away_goals),
        "AWAY": _won(s.home_goals < s.away_goals),
    }


def _double_chance(s: FootballState) -> dict[str, Settlement]:
    return {
        "HOME_OR_DRAW": _won(s.home_goals >= s.away_goals),
        "AWAY_OR_DRAW": _won(s.home_goals <= s.away_goals),
        "HOME_OR_AWAY": _won(s.home_goals != s.away_goals),
    }


def _btts(s: FootballState) -> dict[str, Settlement]:
    both = s.home_goals > 0 and s.away_goals > 0
    return {"YES": _won(both), "NO": _won(not both)}


def _over_under(total: int, line: float) -> dict[str, Settlement]:
    if total == line:
        return {"OVER": Settlement.VOID, "UNDER": Settlement.VOID}
    return {"OVER": _won(total > line), "UNDER": _won(total < line)}


def _total_goals(s: FootballState, line: float) -> dict[str, Settlement]:
    return _over_under(s.home_goals + s.away_goals, line)


def _team_total(s: FootballState, side: str, line: float) -> dict[str, Settlement]:
    return _over_under(s.goals(Side(side)), line)


def _win_margin(s: FootballState, side: str, min_margin: int) -> dict[str, Settlement]:
    if min_margin < 1:
        raise ValueError("min_margin must be at least 1")
    wins_by = s.margin(Side(side)) >= min_margin
    return {"YES": _won(wins_by), "NO": _won(not wins_by)}


def _correct_score(s: FootballState, home: int, away: int) -> dict[str, Settlement]:
    exact = (s.home_goals, s.away_goals) == (home, away)
    return {"YES": _won(exact), "NO": _won(not exact)}


MARKET_TYPES: Mapping[str, MarketType] = {
    m.code: m
    for m in (
        MarketType("MATCH_RESULT", ("HOME", "DRAW", "AWAY"), (), _match_result, "1X2"),
        MarketType(
            "DOUBLE_CHANCE",
            ("HOME_OR_DRAW", "AWAY_OR_DRAW", "HOME_OR_AWAY"),
            (),
            _double_chance,
            "Two of the three results",
        ),
        MarketType("BTTS", ("YES", "NO"), (), _btts, "Both teams to score"),
        MarketType(
            "TOTAL_GOALS", ("OVER", "UNDER"), ("line",), _total_goals, "Match goals over/under"
        ),
        MarketType(
            "TEAM_TOTAL",
            ("OVER", "UNDER"),
            ("side", "line"),
            _team_total,
            "One team's goals over/under",
        ),
        MarketType(
            "WIN_MARGIN",
            ("YES", "NO"),
            ("side", "min_margin"),
            _win_margin,
            "Team wins by at least N goals",
        ),
        MarketType(
            "CORRECT_SCORE", ("YES", "NO"), ("home", "away"), _correct_score, "Exact final score"
        ),
    )
}


@dataclass(frozen=True, slots=True)
class OutcomePrice:
    """Probability the outcome wins, and that the bet is void (a push)."""

    win: float
    void: float

    @property
    def lose(self) -> float:
        return 1.0 - self.win - self.void

    @property
    def win_given_action(self) -> float:
        """P(win | not void): the probability to compare with a price on a line that can push."""
        settled = 1.0 - self.void
        return self.win / settled if settled > 0 else 0.0


def price(
    matrix: NDArray[np.float64], market: MarketType, **params: Any
) -> dict[str, OutcomePrice]:
    """Price every outcome of ``market`` from a score matrix (rows home, columns away)."""
    win = dict.fromkeys(market.outcomes, 0.0)
    void = dict.fromkeys(market.outcomes, 0.0)
    rows, cols = matrix.shape
    for home in range(rows):
        for away in range(cols):
            p = float(matrix[home, away])
            if p == 0.0:
                continue
            for outcome, result in market.settle(FootballState(home, away), **params).items():
                if result is Settlement.WIN:
                    win[outcome] += p
                elif result is Settlement.VOID:
                    void[outcome] += p
    return {o: OutcomePrice(win=win[o], void=void[o]) for o in market.outcomes}


def settle(
    market_code: str, home_goals: int, away_goals: int, **params: Any
) -> dict[str, Settlement]:
    """Grade a finished match with the same rule used for pricing."""
    return MARKET_TYPES[market_code].settle(FootballState(home_goals, away_goals), **params)
