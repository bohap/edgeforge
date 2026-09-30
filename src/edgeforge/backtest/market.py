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
from datetime import datetime, timedelta

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
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


@dataclass(frozen=True, slots=True)
class BlendTest:
    """Does the model add information beyond the market's opening prices?

    Walk-forward fit of ``p ∝ opening^w_market · model^w_model`` on settled earlier matches,
    scored on matches from ``holdout_start``. A model weight near zero means the model adds
    nothing the opening line did not already contain.
    """

    market: str
    matches: int
    model_log_loss: float
    opening_log_loss: float
    blend_log_loss: float
    closing_log_loss: float
    market_weight: float
    model_weight: float


def market_blend_test(
    session: Session,
    result: BacktestResult,
    holdout_start: datetime,
    *,
    bookmaker: str = "market_average",
    min_history: int = 200,
    refit_every: int = 50,
) -> list[BlendTest]:
    tests = []
    for code, _, outcomes in MARKETS:
        if code not in PRICED_MARKETS:
            continue
        rows = sorted((p for p in result.predictions if p.market == code), key=lambda p: p.as_of)
        prices = load_prices(
            session,
            {p.match_id for p in rows},
            bookmaker=bookmaker,
            market_code=code,
            params_key=PRICED_MARKETS[code],
        )
        rows = [
            p
            for p in rows
            if _complete(prices.get(p.match_id), outcomes, "opening")
            and _complete(prices.get(p.match_id), outcomes, "closing")
        ]
        model = np.log(np.clip(np.array([p.model for p in rows]), 1e-12, 1.0))
        opening = np.log(
            np.array(
                [
                    [implied_probabilities(prices[p.match_id].opening)[o] for o in outcomes]
                    for p in rows
                ]
            )
        )
        closing = np.array(
            [[implied_probabilities(prices[p.match_id].closing)[o] for o in outcomes] for p in rows]
        )
        happened = np.array([p.outcome for p in rows])
        as_of = [p.as_of for p in rows]
        holdout = [i for i, t in enumerate(as_of) if t >= holdout_start]

        blended = []
        weights = np.array([1.0, 0.0])
        for n, i in enumerate(holdout):
            if n % refit_every == 0:
                history = [j for j, t in enumerate(as_of) if t + timedelta(days=1) <= as_of[i]]
                if len(history) >= min_history:
                    weights = _fit_blend(opening[history], model[history], happened[history])
            logits = weights[0] * opening[i] + weights[1] * model[i]
            exp = np.exp(logits - logits.max())
            blended.append(exp / exp.sum())
        if not holdout:
            continue
        tests.append(
            BlendTest(
                market=code,
                matches=len(holdout),
                model_log_loss=log_loss(np.exp(model[holdout]), happened[holdout]),
                opening_log_loss=log_loss(np.exp(opening[holdout]), happened[holdout]),
                blend_log_loss=log_loss(np.array(blended), happened[holdout]),
                closing_log_loss=log_loss(closing[holdout], happened[holdout]),
                market_weight=float(weights[0]),
                model_weight=float(weights[1]),
            )
        )
    return tests


def _fit_blend(
    opening: NDArray[np.float64], model: NDArray[np.float64], happened: NDArray[np.int64]
) -> NDArray[np.float64]:
    rows = np.arange(len(happened))

    def objective(w: NDArray[np.float64]) -> float:
        logits = w[0] * opening + w[1] * model
        logits = logits - logits.max(axis=1, keepdims=True)
        log_probs = logits - np.log(np.exp(logits).sum(axis=1, keepdims=True))
        return float(-log_probs[rows, happened].sum())

    return np.asarray(minimize(objective, [1.0, 0.0], method="L-BFGS-B").x)
