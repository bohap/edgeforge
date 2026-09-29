"""Scoring rules and calibration for probabilistic predictions.

``probs`` is an (n, k) array of predicted probabilities over k outcomes and ``outcome`` an
(n,) array of the index that happened.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

EPSILON = 1e-15


def log_loss(probs: NDArray[np.float64], outcome: NDArray[np.int64]) -> float:
    """Mean negative log probability of what happened (lower is better)."""
    picked = probs[np.arange(len(outcome)), outcome]
    return float(-np.mean(np.log(np.clip(picked, EPSILON, 1.0))))


def brier(probs: NDArray[np.float64], outcome: NDArray[np.int64]) -> float:
    """Mean squared error against one-hot outcomes, summed over outcomes (lower is better)."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(outcome)), outcome] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def ranked_probability_score(probs: NDArray[np.float64], outcome: NDArray[np.int64]) -> float:
    """RPS for ordered outcomes (e.g. home, draw, away); penalises distant misses more."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(outcome)), outcome] = 1.0
    cumulative = np.cumsum(probs, axis=1)[:, :-1] - np.cumsum(onehot, axis=1)[:, :-1]
    return float(np.mean(np.sum(cumulative**2, axis=1) / (probs.shape[1] - 1)))


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed: float
    observed_low: float  # 95% Wilson interval
    observed_high: float


def calibration(
    predicted: NDArray[np.float64], happened: NDArray[np.bool_], bins: int = 10
) -> list[CalibrationBin]:
    """Reliability table for binary events: predicted probability vs observed frequency."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(predicted, edges[1:-1]), 0, bins - 1)
    table = []
    for b in range(bins):
        mask = index == b
        n = int(mask.sum())
        if n == 0:
            continue
        freq = float(happened[mask].mean())
        low, high = wilson_interval(int(happened[mask].sum()), n)
        table.append(
            CalibrationBin(
                lower=float(edges[b]),
                upper=float(edges[b + 1]),
                count=n,
                mean_predicted=float(predicted[mask].mean()),
                observed=freq,
                observed_low=low,
                observed_high=high,
            )
        )
    return table


def expected_calibration_error(table: list[CalibrationBin]) -> float:
    total = sum(b.count for b in table)
    if total == 0:
        return 0.0
    return sum(b.count * abs(b.mean_predicted - b.observed) for b in table) / total


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)
