"""Scoring backtest predictions against bookmaker prices.

- Log loss of the model versus the market's de-vigged closing probabilities, on the same
  matches. The closing line is the strongest public benchmark; matching it is already good.
- Simulated flat 1-unit bets wherever the model's expected value at the chosen price exceeds
  a threshold, settled on the actual result, with closing-line value (CLV): how much better
  the price taken was than the closing price.

The model predicts 60 minutes before kickoff, so using the closing price (set at kickoff) as
the benchmark gives the market slightly more information than the model had.
"""

import math
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from edgeforge.backtest.metrics import log_loss
from edgeforge.backtest.walk_forward import MARKETS, BacktestResult, Prediction
from edgeforge.marketdata.odds import MarketPrices, implied_probabilities, load_prices

# Markets with prices in the odds source: (market code, params key used in mkt.historical_odds)
PRICED_MARKETS = {"MATCH_RESULT": "", "TOTAL_GOALS": "line=2.5"}


@dataclass(frozen=True, slots=True)
class BetSimulation:
    price_type: str  # "opening" or "closing"
    min_edge: float
    bets: int
    wins: int
    staked: float
    profit: float
    average_odds: float
    closing_line_value: float | None  # mean(taken / closing - 1); None when betting at closing

    @property
    def roi(self) -> float:
        return self.profit / self.staked if self.staked else 0.0

    @property
    def roi_standard_error(self) -> float:
        """Approximate standard error of the ROI for flat stakes."""
        if self.bets < 2:
            return math.inf
        p = self.wins / self.bets
        variance = p * (self.average_odds - 1) ** 2 + (1 - p) - (self.roi) ** 2
        return math.sqrt(max(variance, 0.0) / self.bets)


@dataclass(frozen=True, slots=True)
class MarketComparison:
    market: str
    bookmaker: str
    matches: int
    model_log_loss: float
    market_log_loss: float
    simulations: list[BetSimulation]


def compare_with_market(
    session: Session,
    result: BacktestResult,
    *,
    bookmaker: str = "market_average",
    edges: tuple[float, ...] = (0.02, 0.05, 0.10),
    min_odds: float = 1.01,
    max_odds: float = 10.0,
) -> list[MarketComparison]:
    comparisons = []
    for code, _, outcomes in MARKETS:
        if code not in PRICED_MARKETS:
            continue
        predictions = [p for p in result.predictions if p.market == code]
        prices = load_prices(
            session,
            {p.match_id for p in predictions},
            bookmaker=bookmaker,
            market_code=code,
            params_key=PRICED_MARKETS[code],
        )
        scored = [p for p in predictions if _complete(prices.get(p.match_id), outcomes, "closing")]
        if not scored:
            continue
        model = np.array([p.model for p in scored])
        market = np.array(
            [
                [implied_probabilities(prices[p.match_id].closing)[o] for o in outcomes]
                for p in scored
            ]
        )
        happened = np.array([p.outcome for p in scored])
        simulations = [
            _simulate(predictions, prices, outcomes, price_type, edge, min_odds, max_odds)
            for price_type in ("opening", "closing")
            for edge in edges
        ]
        comparisons.append(
            MarketComparison(
                market=code,
                bookmaker=bookmaker,
                matches=len(scored),
                model_log_loss=log_loss(model, happened),
                market_log_loss=log_loss(market, happened),
                simulations=simulations,
            )
        )
    return comparisons


def _complete(prices: MarketPrices | None, outcomes: tuple[str, ...], side: str) -> bool:
    if prices is None:
        return False
    book = prices.opening if side == "opening" else prices.closing
    return all(o in book for o in outcomes)


def _simulate(
    predictions: list[Prediction],
    prices: dict[uuid.UUID, MarketPrices],
    outcomes: tuple[str, ...],
    price_type: str,
    min_edge: float,
    min_odds: float,
    max_odds: float,
) -> BetSimulation:
    bets = wins = 0
    profit = odds_sum = 0.0
    clv: list[float] = []
    for p in predictions:
        book = prices.get(p.match_id)
        if book is None or not _complete(book, outcomes, price_type):
            continue
        taken = book.opening if price_type == "opening" else book.closing
        for index, outcome in enumerate(outcomes):
            price = taken[outcome]
            expected_value = p.model[index] * price - 1.0
            if expected_value < min_edge or not min_odds <= price <= max_odds:
                continue
            bets += 1
            odds_sum += price
            if p.outcome == index:
                wins += 1
                profit += price - 1.0
            else:
                profit -= 1.0
            if price_type == "opening" and outcome in book.closing:
                clv.append(price / book.closing[outcome] - 1.0)
    return BetSimulation(
        price_type=price_type,
        min_edge=min_edge,
        bets=bets,
        wins=wins,
        staked=float(bets),
        profit=profit,
        average_odds=odds_sum / bets if bets else 0.0,
        closing_line_value=float(np.mean(clv)) if clv else None,
    )
