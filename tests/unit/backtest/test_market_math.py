import uuid
from datetime import UTC, datetime

import pytest

from edgeforge.backtest.market import _simulate
from edgeforge.backtest.walk_forward import Prediction
from edgeforge.marketdata.odds import MarketPrices, implied_probabilities, overround

T = datetime(2026, 1, 1, tzinfo=UTC)
OUTCOMES = ("HOME", "DRAW", "AWAY")


def _prediction(model: tuple[float, float, float], outcome: int) -> Prediction:
    return Prediction(
        match_id=uuid.uuid4(),
        as_of=T,
        fitted_as_of=T,
        latest_data_kickoff=T,
        market="MATCH_RESULT",
        model=model,
        base_rate=(1 / 3, 1 / 3, 1 / 3),
        outcome=outcome,
    )


def test_implied_probabilities_remove_the_margin() -> None:
    prices = {"HOME": 1.70, "DRAW": 3.80, "AWAY": 5.00}

    probabilities = implied_probabilities(prices)

    assert overround(prices) == pytest.approx(1 / 1.7 + 1 / 3.8 + 1 / 5 - 1)
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert probabilities["HOME"] == pytest.approx((1 / 1.7) / (1 + overround(prices)))


def test_simulation_bets_only_above_the_edge_and_settles_correctly() -> None:
    win = _prediction((0.60, 0.25, 0.15), outcome=0)  # EV home = 0.6*2.0-1 = +0.20
    loss = _prediction((0.60, 0.25, 0.15), outcome=1)  # same bet, loses
    no_bet = _prediction((0.45, 0.30, 0.25), outcome=0)  # EV home = -0.10
    book = MarketPrices(
        opening={"HOME": 2.0, "DRAW": 3.4, "AWAY": 4.0},
        closing={"HOME": 1.8, "DRAW": 3.6, "AWAY": 4.5},
    )
    prices = {p.match_id: book for p in (win, loss, no_bet)}

    sim = _simulate([win, loss, no_bet], prices, OUTCOMES, "opening", 0.05, 1.01, 10.0)

    assert (sim.bets, sim.wins) == (2, 1)
    assert sim.profit == pytest.approx(1.0 - 1.0)
    assert sim.roi == pytest.approx(0.0)
    assert sim.closing_line_value == pytest.approx(2.0 / 1.8 - 1)


def test_simulation_respects_the_odds_band_and_missing_prices() -> None:
    longshot = _prediction((0.05, 0.05, 0.90), outcome=2)  # EV away huge, but odds 12
    unpriced = _prediction((0.90, 0.05, 0.05), outcome=0)
    prices = {
        longshot.match_id: MarketPrices(
            opening={"HOME": 1.2, "DRAW": 7.0, "AWAY": 12.0}, closing={}
        )
    }

    sim = _simulate([longshot, unpriced], prices, OUTCOMES, "opening", 0.0, 1.01, 10.0)

    assert sim.bets == 0
    assert sim.closing_line_value is None
