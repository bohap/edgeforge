"""Reading historical odds and turning prices into probabilities."""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.marketdata.models import HistoricalOdds


@dataclass(frozen=True, slots=True)
class MarketPrices:
    """Opening and closing decimal odds per outcome for one match and market."""

    opening: dict[str, float]
    closing: dict[str, float]


def implied_probabilities(prices: Mapping[str, float]) -> dict[str, float]:
    """Remove the bookmaker margin proportionally: p_i = (1/o_i) / Σ(1/o_j)."""
    inverse = {outcome: 1.0 / price for outcome, price in prices.items()}
    total = sum(inverse.values())
    return {outcome: value / total for outcome, value in inverse.items()}


def overround(prices: Mapping[str, float]) -> float:
    """Bookmaker margin: Σ(1/o) - 1."""
    return sum(1.0 / price for price in prices.values()) - 1.0


def load_prices(
    session: Session,
    match_ids: Iterable[uuid.UUID],
    *,
    bookmaker: str,
    market_code: str,
    params_key: str,
) -> dict[uuid.UUID, MarketPrices]:
    """Prices for each match that has them. A side is included only when complete (every
    outcome priced), so implied probabilities are never computed from partial books."""
    ids = list(match_ids)
    if not ids:
        return {}
    rows = session.scalars(
        select(HistoricalOdds).where(
            HistoricalOdds.match_id.in_(ids),
            HistoricalOdds.bookmaker == bookmaker,
            HistoricalOdds.market_code == market_code,
            HistoricalOdds.params_key == params_key,
        )
    )
    opening: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
    closing: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if row.opening is not None:
            opening[row.match_id][row.outcome] = row.opening
        if row.closing is not None:
            closing[row.match_id][row.outcome] = row.closing
    result = {}
    for match_id in set(opening) | set(closing):
        result[match_id] = MarketPrices(opening=opening[match_id], closing=closing[match_id])
    return result
