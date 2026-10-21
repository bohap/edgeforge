"""Reading prediction-market quotes."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import DataProvider
from edgeforge.marketdata.models import MarketQuote


@dataclass(frozen=True, slots=True)
class Quote:
    """Order book of one outcome. Prices are probabilities; the complement of ``outcome``
    can be bought at ``1 - best_bid``."""

    market_code: str
    params: dict[str, Any]
    outcome: str
    best_bid: float | None
    best_ask: float | None
    liquidity: float | None
    fee_rate: float
    event_slug: str
    observed_at: datetime


def match_quotes(
    session: Session, match_id: uuid.UUID, provider_code: str, as_of: datetime
) -> list[Quote]:
    """The provider's quotes for a match as known at ``as_of``."""
    rows = session.scalars(
        select(MarketQuote)
        .join(DataProvider, DataProvider.id == MarketQuote.provider_id)
        .where(
            MarketQuote.match_id == match_id,
            DataProvider.code == provider_code,
            MarketQuote.observed_at <= as_of,
        )
        .order_by(MarketQuote.market_code, MarketQuote.params_key, MarketQuote.outcome)
    )
    return [
        Quote(
            market_code=q.market_code,
            params=q.params,
            outcome=q.outcome,
            best_bid=q.best_bid,
            best_ask=q.best_ask,
            liquidity=q.liquidity,
            fee_rate=q.fee_rate,
            event_slug=q.event_slug,
            observed_at=q.observed_at,
        )
        for q in rows
    ]
