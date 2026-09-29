"""Typed views of Understat JSON payloads.

Understat sends most numbers as strings; pydantic converts them. Kickoff times are UTC
without a zone marker (verified against known kickoffs), so they are tagged as UTC here.

Unknown fields are allowed and reported by ``unknown_fields`` so a provider change is
visible without breaking ingestion; missing required fields fail validation.

Deliberately dropped: the per-match ``forecast`` in league data. It is computed from that
match's own xG, so using it as a pre-match input would leak the result.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

PARSER_VERSION = "understat-v1"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class UnderstatModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)


# ---------------------------------------------------------------- league data


class TeamRef(UnderstatModel):
    id: int
    title: str
    short_title: str


class HomeAway[T](UnderstatModel):
    h: T
    a: T


class Fixture(UnderstatModel):
    """A league fixture. Future fixtures have no goals or xG."""

    id: int
    is_result: bool = Field(alias="isResult")
    home: TeamRef = Field(alias="h")
    away: TeamRef = Field(alias="a")
    goals: HomeAway[int | None]
    xg: HomeAway[float | None] = Field(alias="xG")
    kickoff_at: UtcDatetime = Field(alias="datetime")

    @model_validator(mode="before")
    @classmethod
    def _drop_forecast(cls, data: Any) -> Any:
        if isinstance(data, dict) and "forecast" in data:
            return {k: v for k, v in data.items() if k != "forecast"}
        return data


class Ppda(UnderstatModel):
    att: int
    defence: int = Field(alias="def")


class TeamMatchHistory(UnderstatModel):
    """One played match from a team's perspective, as listed in league data."""

    h_a: str
    date: UtcDatetime
    xg: float = Field(alias="xG")
    xga: float = Field(alias="xGA")
    npxg: float = Field(alias="npxG")
    npxga: float = Field(alias="npxGA")
    ppda: Ppda
    ppda_allowed: Ppda
    deep: int
    deep_allowed: int
    scored: int
    missed: int
    xpts: float
    result: str
    pts: int


class TeamSeason(UnderstatModel):
    id: int
    title: str
    history: list[TeamMatchHistory]


class PlayerSeason(UnderstatModel):
    id: int
    player_name: str
    team_title: str
    position: str
    games: int
    time: int
    goals: int
    npg: int
    xg: float = Field(alias="xG")
    npxg: float = Field(alias="npxG")
    assists: int
    xa: float = Field(alias="xA")
    shots: int
    key_passes: int
    yellow_cards: int
    red_cards: int
    xg_chain: float = Field(alias="xGChain")
    xg_buildup: float = Field(alias="xGBuildup")


class LeaguePayload(UnderstatModel):
    teams: dict[str, TeamSeason]
    players: list[PlayerSeason]
    dates: list[Fixture]


# ---------------------------------------------------------------- match data


class Shot(UnderstatModel):
    id: int
    match_id: int
    minute: int
    result: str
    x: float = Field(alias="X")
    y: float = Field(alias="Y")
    xg: float = Field(alias="xG")
    player: str
    player_id: int
    h_a: str
    situation: str
    shot_type: str = Field(alias="shotType")
    player_assisted: str | None
    last_action: str | None = Field(alias="lastAction")


class RosterEntry(UnderstatModel):
    id: int
    player_id: int
    team_id: int
    player: str
    position: str
    position_order: int = Field(alias="positionOrder")
    h_a: str
    time: int
    goals: int
    own_goals: int
    shots: int
    xg: float = Field(alias="xG")
    assists: int
    xa: float = Field(alias="xA")
    key_passes: int
    yellow_card: int
    red_card: int
    roster_in: int
    roster_out: int
    xg_chain: float = Field(alias="xGChain")
    xg_buildup: float = Field(alias="xGBuildup")


class MatchPayload(UnderstatModel):
    shots: HomeAway[list[Shot]]
    rosters: HomeAway[dict[str, RosterEntry]]


# ---------------------------------------------------------------- helpers


def unknown_fields(model: BaseModel, path: str = "") -> set[str]:
    """Paths of fields present in the payload but not modelled."""
    found = {f"{path}{name}" for name in (model.model_extra or {})}
    for name in type(model).model_fields:
        found |= _unknown_in(getattr(model, name), f"{path}{name}.")
    return found


def _unknown_in(value: Any, path: str) -> set[str]:
    if isinstance(value, BaseModel):
        return unknown_fields(value, path)
    if isinstance(value, list):
        return set().union(*(_unknown_in(v, f"{path}[].") for v in value)) if value else set()
    if isinstance(value, dict):
        return (
            set().union(*(_unknown_in(v, f"{path}{{}}.") for v in value.values()))
            if value
            else set()
        )
    return set()
