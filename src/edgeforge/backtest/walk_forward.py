"""Walk-forward backtest of the goal model on 1X2, BTTS and over/under 2.5.

For every match in the window the prediction is made as of ``kickoff - lead`` from a model
fitted at the start of its refit window, with data from ``features.played_matches`` only.
A base-rate model (league frequencies known at the same moment) is scored alongside.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from edgeforge.backtest.metrics import (
    brier,
    calibration,
    expected_calibration_error,
    log_loss,
    ranked_probability_score,
)
from edgeforge.features.gateway import PlayedMatch, played_matches
from edgeforge.markets.football import MARKET_TYPES, Settlement, price, settle
from edgeforge.models.football_goals.model import GoalModelConfig, GoalRatings, fit

# (market code, parameters, outcomes in scoring order)
MARKETS: tuple[tuple[str, dict[str, float], tuple[str, ...]], ...] = (
    ("MATCH_RESULT", {}, ("HOME", "DRAW", "AWAY")),
    ("BTTS", {}, ("YES", "NO")),
    ("TOTAL_GOALS", {"line": 2.5}, ("OVER", "UNDER")),
)


@dataclass(frozen=True, slots=True)
class Prediction:
    match_id: uuid.UUID
    as_of: datetime
    fitted_as_of: datetime
    latest_data_kickoff: datetime
    market: str
    model: tuple[float, ...]
    base_rate: tuple[float, ...]
    outcome: int


@dataclass(frozen=True, slots=True)
class MarketScore:
    market: str
    predictions: int
    model_log_loss: float
    base_log_loss: float
    model_brier: float
    base_brier: float
    model_rps: float | None
    model_ece: float


@dataclass(slots=True)
class BacktestResult:
    predictions: list[Prediction] = field(default_factory=list)

    def scores(self) -> list[MarketScore]:
        out = []
        for code, _, outcomes in MARKETS:
            rows = [p for p in self.predictions if p.market == code]
            if not rows:
                continue
            model = np.array([p.model for p in rows])
            base = np.array([p.base_rate for p in rows])
            happened = np.array([p.outcome for p in rows])
            first = np.array([p.model[0] for p in rows])
            out.append(
                MarketScore(
                    market=code,
                    predictions=len(rows),
                    model_log_loss=log_loss(model, happened),
                    base_log_loss=log_loss(base, happened),
                    model_brier=brier(model, happened),
                    base_brier=brier(base, happened),
                    model_rps=ranked_probability_score(model, happened)
                    if len(outcomes) == 3
                    else None,
                    model_ece=expected_calibration_error(calibration(first, happened == 0)),
                )
            )
        return out


def run_backtest(
    session: Session,
    competition_id: uuid.UUID,
    start: datetime,
    end: datetime,
    *,
    config: GoalModelConfig | None = None,
    refit_every: timedelta = timedelta(days=7),
    lead: timedelta = timedelta(minutes=60),
    history: timedelta = timedelta(days=5 * 365),
    min_training_matches: int = 50,
) -> BacktestResult:
    """Predict every match with kickoff in ``[start, end)`` walk-forward."""
    config = config or GoalModelConfig()
    targets = [
        m
        for m in played_matches(session, end + timedelta(days=30), competition_id=competition_id)
        if start <= m.kickoff_at < end
    ]
    result = BacktestResult()
    ratings: GoalRatings | None = None
    training: Sequence[PlayedMatch] = ()
    window_end: datetime | None = None

    for target in targets:
        as_of = target.kickoff_at - lead
        if window_end is None or as_of >= window_end:
            fitted_as_of = as_of
            window_end = as_of + refit_every
            training = played_matches(
                session, fitted_as_of, competition_id=competition_id, since=fitted_as_of - history
            )
            ratings = (
                fit(training, fitted_as_of, config)
                if len(training) >= min_training_matches
                else None
            )
        if ratings is None:
            continue

        matrix = ratings.score_matrix(target.home_team_id, target.away_team_id)
        for code, params, outcomes in MARKETS:
            prices = price(matrix, MARKET_TYPES[code], **params)
            settled = settle(code, target.home_goals, target.away_goals, **params)
            winner = next(i for i, o in enumerate(outcomes) if settled[o] is Settlement.WIN)
            result.predictions.append(
                Prediction(
                    match_id=target.match_id,
                    as_of=as_of,
                    fitted_as_of=ratings.as_of,
                    latest_data_kickoff=max(m.kickoff_at for m in training),
                    market=code,
                    model=tuple(prices[o].win for o in outcomes),
                    base_rate=_base_rate(training, code, params, outcomes),
                    outcome=winner,
                )
            )
    return result


def _base_rate(
    training: Sequence[PlayedMatch], code: str, params: dict[str, float], outcomes: tuple[str, ...]
) -> tuple[float, ...]:
    """Outcome frequencies in the training data, with add-one smoothing."""
    counts = dict.fromkeys(outcomes, 1.0)
    for m in training:
        for outcome, result in settle(code, m.home_goals, m.away_goals, **params).items():
            if result is Settlement.WIN:
                counts[outcome] += 1
    total = sum(counts.values())
    return tuple(counts[o] / total for o in outcomes)
