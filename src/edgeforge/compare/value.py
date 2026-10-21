"""Market prices against the model: each side of each quoted market as decimal odds after
fees, the market's and the model's probability, and the model's expected return (edge).

A side's buy price is the best ask of its token; the complement token costs ``1 - bid``.
Polymarket charges takers ``rate * p * (1 - p)`` per share at price ``p``, so a stake of
``p`` per share pays ``1`` for ``p * (1 + rate * (1 - p))``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from edgeforge.marketdata.quotes import Quote
from edgeforge.markets.football import MARKET_TYPES, price

# Books wider than this, or prices this close to 0 or 1, are not a usable price.
MAX_BOOK_WIDTH = 0.10
MIN_PRICE = 0.02
MAX_PRICE = 0.98


@dataclass(frozen=True, slots=True)
class PricedSide:
    market_code: str
    params: dict[str, Any]
    outcome: str
    negated: bool
    price: float
    odds: float
    market_probability: float
    model_probability: float
    edge: float
    liquidity: float | None
    event_slug: str


def priced_sides(matrix: NDArray[np.float64], quotes: Sequence[Quote]) -> list[PricedSide]:
    """Both sides of every quote with a usable book, priced by the model's score matrix."""
    sides = []
    for q in quotes:
        if q.best_bid is None or q.best_ask is None:
            continue
        if q.best_ask - q.best_bid > MAX_BOOK_WIDTH:
            continue
        market = MARKET_TYPES[q.market_code]
        model = price(matrix, market, **q.params)[q.outcome]
        if model.void > 0:
            continue  # whole-number lines can push; Polymarket lines are n.5
        mid = (q.best_bid + q.best_ask) / 2
        for negated, cost, market_p, model_p in (
            (False, q.best_ask, mid, model.win),
            (True, 1 - q.best_bid, 1 - mid, 1 - model.win),
        ):
            if not MIN_PRICE <= cost <= MAX_PRICE:
                continue
            odds = 1 / (cost * (1 + q.fee_rate * (1 - cost)))
            sides.append(
                PricedSide(
                    market_code=q.market_code,
                    params=q.params,
                    outcome=q.outcome,
                    negated=negated,
                    price=cost,
                    odds=odds,
                    market_probability=market_p,
                    model_probability=model_p,
                    edge=model_p * odds - 1,
                    liquidity=q.liquidity,
                    event_slug=q.event_slug,
                )
            )
    return sides
