"""Fitting team attack/defence ratings.

    log λ_home = μ + h + attack[home] - defence[away]
    log λ_away = μ     + attack[away] - defence[home]

Each past match contributes a weighted Poisson log-likelihood for both teams' target
(``α·xG + (1-α)·goals``; goals alone when xG is missing) with weight
``exp(-ln2 · age_days / half_life_days)``. Normal priors centred on the league average
(0) regularise the ratings, so teams with little data stay near average and promoted teams
start there. The Dixon-Coles ρ is then fitted on actual goals given the fitted rates.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize, minimize_scalar

from edgeforge.features.gateway import PlayedMatch
from edgeforge.models.football_goals.scores import dixon_coles_tau, score_matrix

SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True, slots=True)
class GoalModelConfig:
    half_life_days: float = 180.0
    xg_weight: float = 0.7
    prior_sd_attack: float = 0.3
    prior_sd_defence: float = 0.3
    prior_sd_home: float = 0.2
    rho_bounds: tuple[float, float] = (-0.2, 0.2)
    max_goals: int = 10

    def __post_init__(self) -> None:
        if self.half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        if not 0 <= self.xg_weight <= 1:
            raise ValueError("xg_weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class GoalRatings:
    as_of: datetime
    config: GoalModelConfig
    mu: float
    home_advantage: float
    rho: float
    attack: dict[uuid.UUID, float]
    defence: dict[uuid.UUID, float]
    effective_matches: dict[uuid.UUID, float] = field(default_factory=dict)
    matches_used: int = 0

    def expected_goals(self, home: uuid.UUID, away: uuid.UUID) -> tuple[float, float]:
        """λ for both teams. Teams without data are rated league-average (0)."""
        att, dfn = self.attack, self.defence
        lambda_home = math.exp(
            self.mu + self.home_advantage + att.get(home, 0.0) - dfn.get(away, 0.0)
        )
        lambda_away = math.exp(self.mu + att.get(away, 0.0) - dfn.get(home, 0.0))
        return lambda_home, lambda_away

    def score_matrix(self, home: uuid.UUID, away: uuid.UUID) -> NDArray[np.float64]:
        lambda_home, lambda_away = self.expected_goals(home, away)
        return score_matrix(lambda_home, lambda_away, self.rho, self.config.max_goals)


def fit(
    matches: Sequence[PlayedMatch], as_of: datetime, config: GoalModelConfig | None = None
) -> GoalRatings:
    """Fit ratings from matches known at ``as_of`` (use ``features.played_matches``)."""
    config = config or GoalModelConfig()
    if not matches:
        raise ValueError("no matches to fit")
    if any(m.kickoff_at >= as_of for m in matches):
        raise ValueError("matches must have kicked off before as_of")

    teams = sorted({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    home_idx = np.array([index[m.home_team_id] for m in matches])
    away_idx = np.array([index[m.away_team_id] for m in matches])
    age_days = np.array([(as_of - m.kickoff_at).total_seconds() / SECONDS_PER_DAY for m in matches])
    weights = np.exp(-math.log(2) * age_days / config.half_life_days)
    y_home = np.array([_target(m.home_goals, m.home_xg, config.xg_weight) for m in matches])
    y_away = np.array([_target(m.away_goals, m.away_xg, config.xg_weight) for m in matches])

    def objective(params: NDArray[np.float64]) -> tuple[float, NDArray[np.float64]]:
        mu, home = params[0], params[1]
        att, dfn = params[2 : 2 + n], params[2 + n :]
        log_lh = mu + home + att[home_idx] - dfn[away_idx]
        log_la = mu + att[away_idx] - dfn[home_idx]
        lh, la = np.exp(log_lh), np.exp(log_la)
        # Negative weighted Poisson log-likelihood (constant terms dropped) plus priors.
        nll = -np.sum(weights * (y_home * log_lh - lh + y_away * log_la - la))
        nll += 0.5 * (
            home**2 / config.prior_sd_home**2
            + np.sum(att**2) / config.prior_sd_attack**2
            + np.sum(dfn**2) / config.prior_sd_defence**2
        )
        r_home = weights * (y_home - lh)  # d loglik / d log λ_home
        r_away = weights * (y_away - la)
        grad = np.zeros_like(params)
        grad[0] = -(r_home.sum() + r_away.sum())
        grad[1] = -r_home.sum() + home / config.prior_sd_home**2
        g_att = -(np.bincount(home_idx, r_home, n) + np.bincount(away_idx, r_away, n))
        g_def = np.bincount(away_idx, r_home, n) + np.bincount(home_idx, r_away, n)
        grad[2 : 2 + n] = g_att + att / config.prior_sd_attack**2
        grad[2 + n :] = g_def + dfn / config.prior_sd_defence**2
        return float(nll), grad

    start = np.zeros(2 + 2 * n)
    start[0] = math.log(max((y_home.mean() + y_away.mean()) / 2, 0.1))
    result = minimize(objective, start, jac=True, method="L-BFGS-B")
    if not result.success:
        raise RuntimeError(f"rating fit did not converge: {result.message}")
    params = result.x
    # Only differences between μ, attack and defence are identified by the likelihood.
    # Centre both rating vectors and fold their means into μ; every λ is unchanged.
    att, dfn = params[2 : 2 + n], params[2 + n :]
    mu = float(params[0] + att.mean() - dfn.mean())
    home_advantage = float(params[1])
    attack = {team: float(att[i] - att.mean()) for team, i in index.items()}
    defence = {team: float(dfn[i] - dfn.mean()) for team, i in index.items()}

    rho = _fit_rho(matches, weights, attack, defence, mu, home_advantage, config)
    effective = np.bincount(home_idx, weights, n) + np.bincount(away_idx, weights, n)
    return GoalRatings(
        as_of=as_of,
        config=config,
        mu=mu,
        home_advantage=home_advantage,
        rho=rho,
        attack=attack,
        defence=defence,
        effective_matches={team: float(effective[i]) for team, i in index.items()},
        matches_used=len(matches),
    )


def _target(goals: int, xg: float | None, xg_weight: float) -> float:
    if xg is None:
        return float(goals)
    return xg_weight * xg + (1 - xg_weight) * goals


def _fit_rho(
    matches: Sequence[PlayedMatch],
    weights: NDArray[np.float64],
    attack: dict[uuid.UUID, float],
    defence: dict[uuid.UUID, float],
    mu: float,
    home_advantage: float,
    config: GoalModelConfig,
) -> float:
    lh = np.array(
        [
            math.exp(mu + home_advantage + attack[m.home_team_id] - defence[m.away_team_id])
            for m in matches
        ]
    )
    la = np.array(
        [math.exp(mu + attack[m.away_team_id] - defence[m.home_team_id]) for m in matches]
    )
    hg = np.array([m.home_goals for m in matches])
    ag = np.array([m.away_goals for m in matches])
    low = (hg <= 1) & (ag <= 1)
    if not low.any():
        return 0.0

    def negative_loglik(rho: float) -> float:
        tau = dixon_coles_tau(hg[low], ag[low], lh[low], la[low], rho)
        if np.any(tau <= 0):
            return math.inf
        return float(-np.sum(weights[low] * np.log(tau)))

    lower, upper = config.rho_bounds
    result = minimize_scalar(negative_loglik, bounds=(lower, upper), method="bounded")
    return float(result.x)


__all__ = ["GoalModelConfig", "GoalRatings", "fit", "score_matrix"]
