"""Tables in the ``ref`` schema."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from edgeforge.core.db import Base, IdMixin, TimestampMixin, text_enum

SCHEMA = "ref"


class CompetitionKind(StrEnum):
    LEAGUE = "league"
    CUP = "cup"


class ProviderKind(StrEnum):
    STATS = "stats"
    ODDS = "odds"
    LINEUPS = "lineups"
    MARKET = "market"


class MappingMethod(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class Sport(IdMixin, TimestampMixin, Base):
    __tablename__ = "sport"
    __table_args__ = {"schema": SCHEMA}

    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))


class Competition(IdMixin, TimestampMixin, Base):
    __tablename__ = "competition"
    __table_args__ = (
        UniqueConstraint("sport_id", "code"),
        {"schema": SCHEMA},
    )

    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.sport.id"))
    code: Mapped[str]
    name: Mapped[str]
    country: Mapped[str | None]
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    kind: Mapped[CompetitionKind] = mapped_column(text_enum(CompetitionKind, "competition_kind"))
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    recommendations_enabled: Mapped[bool] = mapped_column(server_default=text("false"))


class Season(IdMixin, TimestampMixin, Base):
    __tablename__ = "season"
    __table_args__ = (
        UniqueConstraint("competition_id", "label"),
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        {"schema": SCHEMA},
    )

    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.competition.id"))
    label: Mapped[str]
    start_date: Mapped[date]
    end_date: Mapped[date]
    is_current: Mapped[bool] = mapped_column(server_default=text("false"))


class DataProvider(IdMixin, TimestampMixin, Base):
    __tablename__ = "data_provider"
    __table_args__ = {"schema": SCHEMA}

    code: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[ProviderKind] = mapped_column(text_enum(ProviderKind, "provider_kind"))
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    reliability_score: Mapped[float | None]
    config: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class ProviderEntityMap(IdMixin, TimestampMixin, Base):
    """Links a provider's external identifier to an internal entity id."""

    __tablename__ = "provider_entity_map"
    __table_args__ = (
        UniqueConstraint("provider_id", "entity_type", "external_id"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        {"schema": SCHEMA},
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.data_provider.id"))
    entity_type: Mapped[str]
    external_id: Mapped[str]
    internal_id: Mapped[uuid.UUID] = mapped_column(index=True)
    method: Mapped[MappingMethod] = mapped_column(text_enum(MappingMethod, "mapping_method"))
    confidence: Mapped[float | None]
    valid_from: Mapped[datetime | None]
    valid_to: Mapped[datetime | None]
