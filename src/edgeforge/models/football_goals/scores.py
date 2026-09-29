"""Score probability matrix from expected goals, with the Dixon-Coles low-score correction."""

import numpy as np
from numpy.typing import NDArray
from scipy.stats import poisson

DEFAULT_MAX_GOALS = 10


def dixon_coles_tau(
    home_goals: NDArray[np.int64],
    away_goals: NDArray[np.int64],
    lambda_home: NDArray[np.float64] | float,
    lambda_away: NDArray[np.float64] | float,
    rho: float,
) -> NDArray[np.float64]:
    """Multiplicative correction for 0-0, 1-0, 0-1 and 1-1 (1 elsewhere)."""
    tau = np.ones(np.broadcast(home_goals, away_goals, lambda_home, lambda_away).shape)
    lh = np.broadcast_to(lambda_home, tau.shape)
    la = np.broadcast_to(lambda_away, tau.shape)
    h = np.broadcast_to(home_goals, tau.shape)
    a = np.broadcast_to(away_goals, tau.shape)
    tau = np.where((h == 0) & (a == 0), 1 - lh * la * rho, tau)
    tau = np.where((h == 0) & (a == 1), 1 + lh * rho, tau)
    tau = np.where((h == 1) & (a == 0), 1 + la * rho, tau)
    tau = np.where((h == 1) & (a == 1), 1 - rho, tau)
    return np.asarray(tau, dtype=np.float64)


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float = 0.0,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> NDArray[np.float64]:
    """P(home = i, away = j) for i, j in 0..max_goals, normalized to sum to 1.

    Rows are home goals, columns away goals. Mass beyond ``max_goals`` (negligible for
    football at the default of 10) is redistributed by the normalization.
    """
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError("expected goals must be positive")
    goals = np.arange(max_goals + 1)
    matrix = np.outer(poisson.pmf(goals, lambda_home), poisson.pmf(goals, lambda_away))
    matrix *= dixon_coles_tau(goals[:, None], goals[None, :], lambda_home, lambda_away, rho)
    if np.any(matrix < 0):
        raise ValueError(f"rho={rho} gives negative probabilities for these expected goals")
    return np.asarray(matrix / matrix.sum(), dtype=np.float64)
