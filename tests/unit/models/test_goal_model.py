import math
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.stats import poisson

from edgeforge.features.gateway import PlayedMatch
from edgeforge.models.football_goals.model import GoalModelConfig, GoalRatings, fit
from edgeforge.models.football_goals.scores import score_matrix

AS_OF = datetime(2026, 9, 1, tzinfo=UTC)
COMPETITION = uuid.UUID(int=1)
SEASON = uuid.UUID(int=2)


def _simulate(
    rng: np.random.Generator,
    attack: dict[uuid.UUID, float],
    defence: dict[uuid.UUID, float],
    *,
    rounds: int,
    mu: float = math.log(1.35),
    home: float = 0.25,
    start: datetime = AS_OF - timedelta(days=720),
    days: float = 700,
    perfect_xg: bool = False,
) -> list[PlayedMatch]:
    teams = list(attack)
    pairs = [(h, a) for h in teams for a in teams if h != a] * rounds
    rng.shuffle(pairs)
    matches = []
    for k, (h, a) in enumerate(pairs):
        lh = math.exp(mu + home + attack[h] - defence[a])
        la = math.exp(mu + attack[a] - defence[h])
        matches.append(
            PlayedMatch(
                match_id=uuid.uuid4(),
                competition_id=COMPETITION,
                season_id=SEASON,
                kickoff_at=start + timedelta(days=days * k / len(pairs)),
                home_team_id=h,
                away_team_id=a,
                home_goals=int(rng.poisson(lh)),
                away_goals=int(rng.poisson(la)),
                home_xg=lh if perfect_xg else None,
                away_xg=la if perfect_xg else None,
                home_npxg=None,
                away_npxg=None,
            )
        )
    return sorted(matches, key=lambda m: m.kickoff_at)


def _league(rng: np.random.Generator, n: int = 12) -> tuple[dict, dict]:
    """True ratings, centred like the fitted ones so μ means the same thing."""
    teams = [uuid.UUID(int=100 + i) for i in range(n)]
    att, dfn = rng.normal(0, 0.3, n), rng.normal(0, 0.3, n)
    attack = {t: float(v) for t, v in zip(teams, att - att.mean(), strict=True)}
    defence = {t: float(v) for t, v in zip(teams, dfn - dfn.mean(), strict=True)}
    return attack, defence


FLAT = GoalModelConfig(half_life_days=1e6, xg_weight=0.0, prior_sd_attack=2.0, prior_sd_defence=2.0)


# ------------------------------------------------------------------ score matrix


def test_score_matrix_is_a_distribution_and_matches_poisson_without_rho() -> None:
    matrix = score_matrix(1.65, 1.10, rho=0.0)
    goals = np.arange(11)
    independent = np.outer(poisson.pmf(goals, 1.65), poisson.pmf(goals, 1.10))

    assert matrix.sum() == pytest.approx(1.0)
    assert matrix == pytest.approx(independent / independent.sum())


def test_score_matrix_reproduces_the_plan_example() -> None:
    m = score_matrix(1.65, 1.10, rho=-0.06)
    i, j = np.indices(m.shape)

    assert m[i > j].sum() == pytest.approx(0.4949, abs=1e-4)
    assert m[i == j].sum() == pytest.approx(0.2584, abs=1e-4)
    assert m[(i > 0) & (j > 0)].sum() == pytest.approx(0.5460, abs=1e-4)
    assert m[i + j > 2.5].sum() == pytest.approx(0.5185, abs=1e-4)
    assert m[1, 1] == pytest.approx(0.123, abs=1e-3)


@pytest.mark.parametrize(("lh", "la", "rho"), [(0.0, 1.0, 0.0), (1.0, -1.0, 0.0), (3.0, 3.0, 0.5)])
def test_score_matrix_rejects_invalid_inputs(lh: float, la: float, rho: float) -> None:
    with pytest.raises(ValueError, match=r"positive|negative probabilities"):
        score_matrix(lh, la, rho)


# ------------------------------------------------------------------ fitting


def test_fit_recovers_true_strengths() -> None:
    rng = np.random.default_rng(7)
    attack, defence = _league(rng)
    matches = _simulate(rng, attack, defence, rounds=4)

    ratings = fit(matches, AS_OF, FLAT)

    teams = list(attack)
    est_att = [ratings.attack[t] for t in teams]
    est_def = [ratings.defence[t] for t in teams]
    assert np.corrcoef(est_att, [attack[t] for t in teams])[0, 1] > 0.85
    assert np.corrcoef(est_def, [defence[t] for t in teams])[0, 1] > 0.85
    assert ratings.home_advantage == pytest.approx(0.25, abs=0.1)
    assert math.exp(ratings.mu) == pytest.approx(1.35, abs=0.15)
    assert ratings.config.rho_bounds[0] <= ratings.rho <= ratings.config.rho_bounds[1]
    assert ratings.matches_used == len(matches)


def test_xg_input_reduces_rating_error() -> None:
    rng = np.random.default_rng(11)
    attack, defence = _league(rng)
    matches = _simulate(rng, attack, defence, rounds=2, perfect_xg=True)
    truth = np.array([attack[t] for t in attack])

    def error(xg_weight: float) -> float:
        config = GoalModelConfig(
            half_life_days=1e6, xg_weight=xg_weight, prior_sd_attack=2.0, prior_sd_defence=2.0
        )
        ratings = fit(matches, AS_OF, config)
        estimate = np.array([ratings.attack[t] for t in attack])
        return float(np.sqrt(np.mean((estimate - truth) ** 2)))

    assert error(1.0) < 0.6 * error(0.0)


def test_short_half_life_follows_recent_form() -> None:
    """A team drops from +0.6 to -0.6 attack a year ago. With noise-free xG as input, a short
    memory lands on the recent side and well below a long memory, which averages both."""
    rng = np.random.default_rng(3)
    attack, defence = _league(rng, n=10)
    changer = next(iter(attack))
    old = _simulate(
        rng,
        {**attack, changer: 0.6},
        defence,
        rounds=2,
        start=AS_OF - timedelta(days=720),
        days=350,
        perfect_xg=True,
    )
    recent = _simulate(
        rng,
        {**attack, changer: -0.6},
        defence,
        rounds=2,
        start=AS_OF - timedelta(days=360),
        days=350,
        perfect_xg=True,
    )
    matches = sorted(old + recent, key=lambda m: m.kickoff_at)

    def ratings(half_life: float) -> GoalRatings:
        config = GoalModelConfig(
            half_life_days=half_life, xg_weight=1.0, prior_sd_attack=1.0, prior_sd_defence=1.0
        )
        return fit(matches, AS_OF, config)

    long_memory, short_memory = ratings(5000), ratings(90)

    assert short_memory.attack[changer] < long_memory.attack[changer] - 0.4
    assert short_memory.attack[changer] < -0.2
    assert long_memory.attack[changer] > 0.0
    assert short_memory.effective_matches[changer] < long_memory.effective_matches[changer]


def test_ratings_are_centred() -> None:
    rng = np.random.default_rng(13)
    attack, defence = _league(rng, n=8)
    ratings = fit(_simulate(rng, attack, defence, rounds=2), AS_OF)

    assert sum(ratings.attack.values()) == pytest.approx(0.0, abs=1e-9)
    assert sum(ratings.defence.values()) == pytest.approx(0.0, abs=1e-9)


def test_teams_without_data_are_league_average() -> None:
    rng = np.random.default_rng(5)
    attack, defence = _league(rng, n=6)
    ratings = fit(_simulate(rng, attack, defence, rounds=2), AS_OF)
    promoted_a, promoted_b = uuid.uuid4(), uuid.uuid4()

    lh, la = ratings.expected_goals(promoted_a, promoted_b)

    assert lh == pytest.approx(math.exp(ratings.mu + ratings.home_advantage))
    assert la == pytest.approx(math.exp(ratings.mu))
    assert ratings.score_matrix(promoted_a, promoted_b).sum() == pytest.approx(1.0)


def test_priors_keep_sparse_teams_near_average() -> None:
    rng = np.random.default_rng(9)
    attack, defence = _league(rng, n=8)
    matches = _simulate(rng, attack, defence, rounds=1)[:10]

    ratings = fit(matches, AS_OF, GoalModelConfig(prior_sd_attack=0.05, prior_sd_defence=0.05))

    assert max(abs(v) for v in ratings.attack.values()) < 0.1


def test_matches_at_or_after_as_of_are_rejected() -> None:
    rng = np.random.default_rng(1)
    attack, defence = _league(rng, n=4)
    matches = _simulate(rng, attack, defence, rounds=1)

    with pytest.raises(ValueError, match="before as_of"):
        fit(matches, matches[-1].kickoff_at)
    with pytest.raises(ValueError, match="no matches"):
        fit([], AS_OF)


@pytest.mark.parametrize("kwargs", [{"half_life_days": 0}, {"xg_weight": 1.5}, {"xg_weight": -0.1}])
def test_invalid_config(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must be"):
        GoalModelConfig(**kwargs)
