"""Tables in the ``mkt`` schema."""

import uuid
from datetime import datetime

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
