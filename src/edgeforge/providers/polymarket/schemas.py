"""The parts of Polymarket's Gamma API responses we use.

Unknown fields are ignored. ``project_events`` keeps only these fields and the market types
we price, so a stored raw payload is a few kilobytes per game instead of hundreds.
"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

PARSER_VERSION = "polymarket-v1"

# Market types we can price from the score matrix.
PRICED_TYPES = frozenset(
    {"moneyline", "spreads", "totals", "both_teams_to_score", "soccer_team_totals"}
)


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


class Team(Model):
    name: str
    alias: str | None = None
    ordering: str | None = None


class FeeSchedule(Model):
    rate: float = 0.0
    taker_only: bool = Field(default=True, alias="takerOnly")


class Market(Model):
    condition_id: str = Field(alias="conditionId")
    question: str
    market_type: str | None = Field(default=None, alias="sportsMarketType")
    line: float | None = None
    title: str | None = Field(default=None, alias="groupItemTitle")
    outcomes: list[str]
    best_bid: float | None = Field(default=None, alias="bestBid")
    best_ask: float | None = Field(default=None, alias="bestAsk")
    last_trade_price: float | None = Field(default=None, alias="lastTradePrice")
    liquidity: float | None = Field(default=None, alias="liquidityNum")
    fees_enabled: bool = Field(default=False, alias="feesEnabled")
    fee_schedule: FeeSchedule | None = Field(default=None, alias="feeSchedule")
    closed: bool = False
    accepting_orders: bool = Field(default=True, alias="acceptingOrders")

    @field_validator("outcomes", mode="before")
    @classmethod
    def _json_list(cls, value: Any) -> Any:
        # The API encodes some lists as JSON strings.
        return json.loads(value) if isinstance(value, str) else value

    @property
    def taker_fee_rate(self) -> float:
        if not self.fees_enabled or self.fee_schedule is None:
            return 0.0
        return self.fee_schedule.rate


class Event(Model):
    slug: str
    title: str
    start_time: datetime | None = Field(default=None, alias="startTime")
    game_id: str | None = Field(default=None, alias="gameId")
    closed: bool = False
    teams: list[Team] = Field(default_factory=list)
    markets: list[Market] = Field(default_factory=list)

    @field_validator("game_id", mode="before")
    @classmethod
    def _str_id(cls, value: Any) -> Any:
        return None if value is None else str(value)

    @property
    def is_game(self) -> bool:
        """The main event of a game (not "More Markets", "Exact Score", props, ...)."""
        return self.game_id is not None and len(self.teams) == 2 and " - " not in self.title


def parse_events(body: bytes) -> list[Event]:
    return [Event.model_validate(item) for item in json.loads(body)]


def project_events(body: bytes) -> bytes:
    """Keep the fields above and only the priced markets, as compact JSON."""
    events = []
    for event in parse_events(body):
        kept = [m for m in event.markets if m.market_type in PRICED_TYPES]
        projected = event.model_copy(update={"markets": kept})
        events.append(projected.model_dump(mode="json", by_alias=True))
    return json.dumps(events, separators=(",", ":"), sort_keys=True).encode()
