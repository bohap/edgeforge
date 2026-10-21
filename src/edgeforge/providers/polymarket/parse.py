"""Turn a game's Polymarket markets into quotes on our market types.

Every Polymarket market here is binary. A quote holds the order book of its first outcome
("Yes", "Over", or the named team on a spread), mapped to one outcome of our market types:

==============================  ============================================
Polymarket                      Ours (outcome of the first token)
==============================  ============================================
moneyline "Will X win?"         MATCH_RESULT HOME / AWAY
moneyline "... end in a draw?"  MATCH_RESULT DRAW
spreads "X (-1.5)"              WIN_MARGIN side=X min_margin=2, YES
totals "O/U 2.5"                TOTAL_GOALS line=2.5, OVER
both_teams_to_score             BTTS YES
soccer_team_totals "X O/U 1.5"  TEAM_TOTAL side=X line=1.5, OVER
==============================  ============================================

The second token pays on the complement, so its buy price is ``1 - best_bid``.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edgeforge.providers.polymarket.schemas import PRICED_TYPES, Event, Market, Team


@dataclass(frozen=True, slots=True)
class Quote:
    market_code: str
    params: dict[str, Any]
    outcome: str
    condition_id: str
    event_slug: str
    best_bid: float | None
    best_ask: float | None
    last_price: float | None
    liquidity: float | None
    fee_rate: float

    @property
    def params_key(self) -> str:
        return params_key(self.params)


def params_key(params: dict[str, Any]) -> str:
    """Stable text key for market parameters: ``line=2.5;side=home``."""
    return ";".join(f"{k}={v}" for k, v in sorted(params.items()))


@dataclass(frozen=True, slots=True)
class GameTeams:
    home: Team
    away: Team


def game_teams(event: Event) -> GameTeams | None:
    """Home and away team of a game event, from Polymarket's ``ordering`` (title order as a
    fallback: "Home vs. Away")."""
    if len(event.teams) != 2:
        return None
    by_order = {t.ordering: t for t in event.teams}
    if "home" in by_order and "away" in by_order:
        return GameTeams(home=by_order["home"], away=by_order["away"])
    first, second = event.teams
    if event.title.startswith(second.name):
        first, second = second, first
    return GameTeams(home=first, away=second)


def game_quotes(events: Sequence[Event], teams: GameTeams) -> tuple[list[Quote], int]:
    """Quotes from a game's events (main + "More Markets"). Returns (quotes, skipped), where
    skipped counts open markets of a priced type we could not map."""
    quotes: list[Quote] = []
    skipped = 0
    for event in events:
        for market in event.markets:
            if market.closed or not market.accepting_orders:
                continue
            if market.market_type not in PRICED_TYPES:
                continue
            mapped = _map(market, teams)
            if mapped is None:
                skipped += 1
                continue
            code, params, outcome = mapped
            quotes.append(
                Quote(
                    market_code=code,
                    params=params,
                    outcome=outcome,
                    condition_id=market.condition_id,
                    event_slug=event.slug,
                    best_bid=market.best_bid,
                    best_ask=market.best_ask,
                    last_price=market.last_trade_price,
                    liquidity=market.liquidity,
                    fee_rate=market.taker_fee_rate,
                )
            )
    return quotes, skipped


def _map(market: Market, teams: GameTeams) -> tuple[str, dict[str, Any], str] | None:
    side = _side(market, teams)
    match market.market_type:
        case "moneyline":
            if market.title is not None and market.title.startswith("Draw"):
                return "MATCH_RESULT", {}, "DRAW"
            return ("MATCH_RESULT", {}, side.upper()) if side else None
        case "spreads":
            if side is None or not _half_line(market.line) or market.line is None:
                return None
            if market.line > 0:
                return None  # only "X (-n.5)": X wins by more than n
            return "WIN_MARGIN", {"side": side, "min_margin": math.ceil(-market.line)}, "YES"
        case "totals":
            if not _half_line(market.line) or market.outcomes[:1] != ["Over"]:
                return None
            return "TOTAL_GOALS", {"line": market.line}, "OVER"
        case "both_teams_to_score":
            return ("BTTS", {}, "YES") if market.outcomes[:1] == ["Yes"] else None
        case "soccer_team_totals":
            if side is None or not _half_line(market.line) or market.outcomes[:1] != ["Over"]:
                return None
            return "TEAM_TOTAL", {"side": side, "line": market.line}, "OVER"
    return None


def _side(market: Market, teams: GameTeams) -> str | None:
    """Which team a market is about, from its title or first outcome."""
    for side, team in (("home", teams.home), ("away", teams.away)):
        if market.market_type == "spreads":
            if market.outcomes[:1] == [team.name]:
                return side
        elif market.title is not None and market.title.startswith(team.name):
            return side
    return None


def _half_line(line: float | None) -> bool:
    return line is not None and abs(line % 1 - 0.5) < 1e-9
