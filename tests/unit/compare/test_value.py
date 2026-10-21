from datetime import UTC, datetime
from typing import Any

import pytest

from edgeforge.compare.value import priced_sides
from edgeforge.marketdata.quotes import Quote
from edgeforge.models.football_goals.scores import score_matrix

MATRIX = score_matrix(1.46, 1.66, rho=-0.05)
NOW = datetime(2026, 10, 21, tzinfo=UTC)


def _quote(
    code: str,
    outcome: str,
    bid: float | None,
    ask: float | None,
    params: dict[str, Any] | None = None,
    fee: float = 0.05,
) -> Quote:
    return Quote(
        market_code=code,
        params=params or {},
        outcome=outcome,
        best_bid=bid,
        best_ask=ask,
        liquidity=1000.0,
        fee_rate=fee,
        event_slug="epl-ips-not-2026-10-23-more-markets",
        observed_at=NOW,
    )


def test_both_sides_are_priced_with_fees() -> None:
    over, under = priced_sides(MATRIX, [_quote("TOTAL_GOALS", "OVER", 0.54, 0.55, {"line": 2.5})])

    assert not over.negated
    assert over.price == pytest.approx(0.55)
    assert over.odds == pytest.approx(1 / (0.55 * (1 + 0.05 * 0.45)))
    assert over.market_probability == pytest.approx(0.545)
    assert under.negated
    assert under.price == pytest.approx(0.46)
    assert under.market_probability == pytest.approx(0.455)
    assert over.model_probability + under.model_probability == pytest.approx(1)
    assert over.edge == pytest.approx(over.model_probability * over.odds - 1)


def test_without_fees_odds_are_the_inverse_price() -> None:
    (yes, _) = priced_sides(MATRIX, [_quote("BTTS", "YES", 0.58, 0.60, fee=0.0)])
    assert yes.odds == pytest.approx(1 / 0.60)


def test_model_probability_comes_from_the_score_matrix() -> None:
    sides = priced_sides(
        MATRIX,
        [
            _quote("MATCH_RESULT", "HOME", 0.30, 0.31),
            _quote("MATCH_RESULT", "DRAW", 0.27, 0.28),
            _quote("MATCH_RESULT", "AWAY", 0.41, 0.42),
        ],
    )
    quoted = [s for s in sides if not s.negated]
    assert sum(s.model_probability for s in quoted) == pytest.approx(1)
    away = next(s for s in quoted if s.outcome == "AWAY")
    assert away.model_probability > next(s for s in quoted if s.outcome == "HOME").model_probability


def test_unusable_books_are_skipped() -> None:
    sides = priced_sides(
        MATRIX,
        [
            _quote("TOTAL_GOALS", "OVER", None, 0.5, {"line": 7.5}),  # no bid
            _quote("TOTAL_GOALS", "OVER", 0.1, 0.4, {"line": 3.5}),  # book too wide
            _quote("TOTAL_GOALS", "OVER", 0.985, 0.99, {"line": 0.5}),  # both sides extreme
        ],
    )
    assert sides == []


def test_only_the_extreme_side_is_dropped() -> None:
    sides = priced_sides(MATRIX, [_quote("TOTAL_GOALS", "OVER", 0.015, 0.03, {"line": 6.5})])
    assert [s.negated for s in sides] == [False]
