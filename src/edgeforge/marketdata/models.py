"""Tables in the ``mkt`` schema."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from edgeforge.core.db import Base, TimestampMixin

SCHEMA = "mkt"


class HistoricalOdds(TimestampMixin, Base):
    """Decimal odds for one outcome from one bookmaker. ``opening`` was published before the
    match (typically days ahead); ``closing`` is the last price before kickoff."""

    __tablename__ = "historical_odds"
    __table_args__ = {"schema": SCHEMA}

    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.match.id"), primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref.data_provider.id"), primary_key=True
    )
    bookmaker: Mapped[str] = mapped_column(primary_key=True)
    market_code: Mapped[str] = mapped_column(primary_key=True)
    params_key: Mapped[str] = mapped_column(primary_key=True)
    outcome: Mapped[str] = mapped_column(primary_key=True)
    opening: Mapped[float | None]
    closing: Mapped[float | None]
    source_raw_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw.raw_payload.id"))
    observed_at: Mapped[datetime]


class MarketQuote(TimestampMixin, Base):
    """Latest pre-kickoff order-book quote for one outcome on a prediction market.

    Prices are probabilities (0-1) for the outcome named in ``outcome``; its complement can
    be bought at ``1 - best_bid``. Rows stop changing at kickoff, so after the match they hold
    the last pre-match quote.
    """

    __tablename__ = "market_quote"
    __table_args__ = {"schema": SCHEMA}

    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.match.id"), primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref.data_provider.id"), primary_key=True
    )
    market_code: Mapped[str] = mapped_column(primary_key=True)
    params_key: Mapped[str] = mapped_column(primary_key=True)
    outcome: Mapped[str] = mapped_column(primary_key=True)
    params: Mapped[dict[str, Any]]
    best_bid: Mapped[float | None]
    best_ask: Mapped[float | None]
    last_price: Mapped[float | None]
    liquidity: Mapped[float | None]
    fee_rate: Mapped[float]
    external_id: Mapped[str]
    event_slug: Mapped[str]
    source_raw_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw.raw_payload.id"))
    observed_at: Mapped[datetime]
