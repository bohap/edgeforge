"""Post-hoc recalibration of multi-outcome probabilities.

    p'_k ∝ p_k^a · exp(b_k),  b_0 = 0

One shared power ``a`` (a < 1 pulls probabilities toward each other, a > 1 spreads them) plus
per-outcome biases (e.g. a draw bias). It keeps probabilities summing to 1 and preserves
their order within each bias class. It is fitted by maximum likelihood on predictions whose
results were known, so applying it walk-forward uses no future information.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class PowerCalibrator:
    power: float
    bias: tuple[float, ...]

    @classmethod
    def identity(cls, outcomes: int) -> PowerCalibrator:
        return cls(power=1.0, bias=(0.0,) * outcomes)

    def apply(self, probs: NDArray[np.float64]) -> NDArray[np.float64]:
        logits = self.power * np.log(np.clip(probs, EPSILON, 1.0)) + np.asarray(self.bias)
        logits -= logits.max(axis=-1, keepdims=True)
        weights = np.exp(logits)
        return np.asarray(weights / weights.sum(axis=-1, keepdims=True), dtype=np.float64)


def fit_power_calibrator(
    probs: NDArray[np.float64], outcome: NDArray[np.int64], *, l2: float = 1.0
) -> PowerCalibrator:
    """Maximum-likelihood fit with a small ridge penalty toward the identity."""
    n, k = probs.shape
    if n == 0:
        return PowerCalibrator.identity(k)
    log_p = np.log(np.clip(probs, EPSILON, 1.0))
    rows = np.arange(n)

    def objective(params: NDArray[np.float64]) -> float:
        power, bias = params[0], np.concatenate(([0.0], params[1:]))
        logits = power * log_p + bias
        logits -= logits.max(axis=1, keepdims=True)
        log_norm = np.log(np.exp(logits).sum(axis=1))
        nll = -np.sum(logits[rows, outcome] - log_norm)
        return float(nll + 0.5 * l2 * ((power - 1.0) ** 2 + np.sum(params[1:] ** 2)))

    start = np.concatenate(([1.0], np.zeros(k - 1)))
    result = minimize(
        objective, start, method="L-BFGS-B", bounds=[(0.2, 3.0)] + [(-2, 2)] * (k - 1)
    )
    return PowerCalibrator(power=float(result.x[0]), bias=(0.0, *map(float, result.x[1:])))
