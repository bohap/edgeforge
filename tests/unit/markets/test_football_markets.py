import itertools

import numpy as np
import pytest

from edgeforge.markets.football import (
    MARKET_TYPES,
    FootballState,
    Settlement,
    Side,
    price,
    settle,
)
from edgeforge.models.football_goals.scores import score_matrix

MATRIX = score_matrix(1.65, 1.10, rho=-0.06)

PARAMS: dict[str, list[dict[str, object]]] = {
    "MATCH_RESULT": [{}],
    "DOUBLE_CHANCE": [{}],
    "BTTS": [{}],
    "TOTAL_GOALS": [{"line": line} for line in (0.5, 1.5, 2.0, 2.5, 3.5)],
    "TEAM_TOTAL": [{"side": s, "line": line} for s in ("home", "away") for line in (0.5, 1.0, 1.5)],
    "WIN_MARGIN": [{"side": s, "min_margin": k} for s in ("home", "away") for k in (1, 2, 3)],
    "CORRECT_SCORE": [{"home": 1, "away": 1}, {"home": 2, "away": 0}],
}


def test_every_registered_market_has_test_parameters() -> None:
    assert set(PARAMS) == set(MARKET_TYPES)


@pytest.mark.parametrize(
    ("code", "params"),
    [(code, p) for code, options in PARAMS.items() for p in options],
)
def test_prices_are_probabilities(code: str, params: dict[str, object]) -> None:
    prices = price(MATRIX, MARKET_TYPES[code], **params)

    for outcome in prices.values():
        assert 0.0 <= outcome.win <= 1.0
        assert 0.0 <= outcome.void <= 1.0
        assert outcome.lose >= -1e-12


@pytest.mark.parametrize("code", ["MATCH_RESULT", "BTTS", "TOTAL_GOALS", "TEAM_TOTAL"])
def test_mutually_exclusive_outcomes_cover_every_score(code: str) -> None:
    for params in PARAMS[code]:
        prices = price(MATRIX, MARKET_TYPES[code], **params).values()
        void = next(iter(prices)).void
        assert sum(p.win for p in prices) + void == pytest.approx(1.0)


def test_matches_the_plan_example() -> None:
    result = price(MATRIX, MARKET_TYPES["MATCH_RESULT"])
    btts = price(MATRIX, MARKET_TYPES["BTTS"])
    over25 = price(MATRIX, MARKET_TYPES["TOTAL_GOALS"], line=2.5)
    home_over_15 = price(MATRIX, MARKET_TYPES["TEAM_TOTAL"], side="home", line=1.5)
    home_by_2 = price(MATRIX, MARKET_TYPES["WIN_MARGIN"], side="home", min_margin=2)

    assert result["HOME"].win == pytest.approx(0.4949, abs=1e-4)
    assert result["DRAW"].win == pytest.approx(0.2584, abs=1e-4)
    assert result["AWAY"].win == pytest.approx(0.2466, abs=1e-4)
    assert btts["YES"].win == pytest.approx(0.5460, abs=1e-4)
    assert over25["OVER"].win == pytest.approx(0.5185, abs=1e-4)
    assert home_over_15["OVER"].win == pytest.approx(0.4911, abs=1e-4)
    assert home_by_2["YES"].win == pytest.approx(0.2669, abs=1e-4)


def test_whole_number_line_pushes_on_exact_total() -> None:
    prices = price(MATRIX, MARKET_TYPES["TOTAL_GOALS"], line=2.0)
    i, j = np.indices(MATRIX.shape)

    assert prices["OVER"].void == pytest.approx(MATRIX[i + j == 2].sum())
    assert prices["OVER"].win_given_action == pytest.approx(
        prices["OVER"].win / (1 - prices["OVER"].void)
    )
    assert settle("TOTAL_GOALS", 1, 1, line=2.0) == {
        "OVER": Settlement.VOID,
        "UNDER": Settlement.VOID,
    }


def test_double_chance_equals_sums_of_results() -> None:
    result = price(MATRIX, MARKET_TYPES["MATCH_RESULT"])
    double = price(MATRIX, MARKET_TYPES["DOUBLE_CHANCE"])

    assert double["HOME_OR_DRAW"].win == pytest.approx(result["HOME"].win + result["DRAW"].win)
    assert double["HOME_OR_AWAY"].win == pytest.approx(1 - result["DRAW"].win)


def test_pricing_and_settlement_agree_on_every_score() -> None:
    """Pricing a one-hot matrix must equal settling that score, for every market."""
    for home, away in itertools.product(range(5), range(5)):
        one_hot = np.zeros((11, 11))
        one_hot[home, away] = 1.0
        for code, options in PARAMS.items():
            for params in options:
                settled = settle(code, home, away, **params)
                priced = price(one_hot, MARKET_TYPES[code], **params)
                for outcome, result in settled.items():
                    assert priced[outcome].win == (1.0 if result is Settlement.WIN else 0.0)
                    assert priced[outcome].void == (1.0 if result is Settlement.VOID else 0.0)


def test_settlement_examples() -> None:
    assert settle("MATCH_RESULT", 2, 1)["HOME"] is Settlement.WIN
    assert settle("BTTS", 2, 0)["YES"] is Settlement.LOSE
    assert settle("WIN_MARGIN", 1, 3, side="away", min_margin=2)["YES"] is Settlement.WIN
    assert settle("TEAM_TOTAL", 0, 2, side="away", line=1.5)["OVER"] is Settlement.WIN
    assert FootballState(3, 1).margin(Side.AWAY) == -2


def test_wrong_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="expects parameters"):
        settle("TOTAL_GOALS", 1, 0)
    with pytest.raises(ValueError, match="min_margin"):
        settle("WIN_MARGIN", 1, 0, side="home", min_margin=0)
