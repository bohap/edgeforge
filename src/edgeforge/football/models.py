"""Tables in the ``core`` schema.

Every provider-derived row records where it came from (``provider_id``, ``source_raw_id``)
and two times:

- ``observed_at``: when we fetched the data.
- ``available_at``: when the information was plausibly public. For live ingestion this equals
  ``observed_at``; for backfilled history it is capped at kickoff plus a fixed lag. Features
  for a prediction at time T may only use rows with ``available_at <= T``.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from edgeforge.core.db import Base, IdMixin, TimestampMixin, text_enum

SCHEMA = "core"


class MatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    FINISHED = "finished"


class ProvenanceMixin:
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.data_provider.id"))
    source_raw_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw.raw_payload.id"))
    observed_at: Mapped[datetime]


class Team(IdMixin, TimestampMixin, Base):
    __tablename__ = "team"
    __table_args__ = {"schema": SCHEMA}

    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.sport.id"))
    name: Mapped[str]
    short_name: Mapped[str | None]


class TeamSeason(Base):
    __tablename__ = "team_season"
    __table_args__ = {"schema": SCHEMA}

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"), primary_key=True)
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.season.id"), primary_key=True)


class Match(IdMixin, TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "match"
    __table_args__ = {"schema": SCHEMA}

    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.competition.id"))
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.season.id"), index=True)
    home_team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"))
    away_team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"))
    kickoff_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[MatchStatus] = mapped_column(text_enum(MatchStatus, "match_status"))


class MatchResult(TimestampMixin, ProvenanceMixin, Base):
    """Score after 90 minutes plus stoppage time."""

    __tablename__ = "match_result"
    __table_args__ = {"schema": SCHEMA}

    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.match.id"), primary_key=True)
    home_goals: Mapped[int] = mapped_column(SmallInteger)
    away_goals: Mapped[int] = mapped_column(SmallInteger)
    available_at: Mapped[datetime]


class MatchTeamStats(TimestampMixin, ProvenanceMixin, Base):
    """One team's statistics in one match. Missing statistics are NULL, never zero."""

    __tablename__ = "match_team_stats"
    __table_args__ = (
        UniqueConstraint("match_id", "is_home"),
        {"schema": SCHEMA},
    )

    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.match.id"), primary_key=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"), primary_key=True)
    is_home: Mapped[bool]
    goals: Mapped[int] = mapped_column(SmallInteger)
    xg: Mapped[float | None]
    npxg: Mapped[float | None]
    ppda_passes: Mapped[int | None]
    ppda_defensive_actions: Mapped[int | None]
    deep_completions: Mapped[int | None]
    available_at: Mapped[datetime]


class Player(IdMixin, TimestampMixin, Base):
    __tablename__ = "player"
    __table_args__ = {"schema": SCHEMA}

    sport_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.sport.id"))
    name: Mapped[str]


class PlayerMatchStats(TimestampMixin, ProvenanceMixin, Base):
    """One player's appearance in one match (only players who played appear)."""

    __tablename__ = "player_match_stats"
    __table_args__ = {"schema": SCHEMA}

    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.match.id"), primary_key=True)
    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.player.id"), primary_key=True, index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"))
    position: Mapped[str]
    started: Mapped[bool]
    minutes: Mapped[int] = mapped_column(SmallInteger)
    goals: Mapped[int] = mapped_column(SmallInteger)
    own_goals: Mapped[int] = mapped_column(SmallInteger)
    shots: Mapped[int] = mapped_column(SmallInteger)
    xg: Mapped[float | None]
    assists: Mapped[int] = mapped_column(SmallInteger)
    xa: Mapped[float | None]
    key_passes: Mapped[int] = mapped_column(SmallInteger)
    yellow_cards: Mapped[int] = mapped_column(SmallInteger)
    red_cards: Mapped[int] = mapped_column(SmallInteger)
    xg_chain: Mapped[float | None]
    xg_buildup: Mapped[float | None]
    available_at: Mapped[datetime]


class Shot(IdMixin, TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "shot"
    __table_args__ = (
        UniqueConstraint("provider_id", "external_id"),
        {"schema": SCHEMA},
    )

    external_id: Mapped[str]
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.match.id"), index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.team.id"))
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.player.id"), index=True)
    assister_name: Mapped[str | None]
    minute: Mapped[int] = mapped_column(SmallInteger)
    x: Mapped[float]
    y: Mapped[float]
    xg: Mapped[float]
    result: Mapped[str]
    situation: Mapped[str]
    shot_type: Mapped[str]
    last_action: Mapped[str | None]
    is_goal: Mapped[bool]
    is_penalty: Mapped[bool]
    available_at: Mapped[datetime]
