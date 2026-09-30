import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np

from edgeforge.backtest.market import _fit_blend
from edgeforge.backtest.recalibrate import recalibrate
from edgeforge.backtest.walk_forward import BacktestResult, Prediction

START = datetime(2024, 1, 1, tzinfo=UTC)


def _predictions(n: int, rng: np.random.Generator) -> list[Prediction]:
    rows = []
    for k in range(n):
        truth = rng.dirichlet([3, 2, 2])
        reported = truth**2 / (truth**2).sum()
        rows.append(
            Prediction(
                match_id=uuid.uuid4(),
                as_of=START + timedelta(days=k),
                fitted_as_of=START + timedelta(days=k),
                latest_data_kickoff=START + timedelta(days=k - 1),
                market="MATCH_RESULT",
                model=tuple(float(x) for x in reported),
                base_rate=(1 / 3, 1 / 3, 1 / 3),
                outcome=int(rng.choice(3, p=truth)),
            )
        )
    return rows


def test_predictions_before_enough_history_are_unchanged() -> None:
    rows = _predictions(400, np.random.default_rng(2))

    calibrated = recalibrate(BacktestResult(rows), min_history=300).predictions

    assert [p.model for p in calibrated[:300]] == [p.model for p in rows[:300]]
    assert any(c.model != r.model for c, r in zip(calibrated[300:], rows[300:], strict=True))


def test_later_outcomes_cannot_change_earlier_calibration() -> None:
    rows = _predictions(500, np.random.default_rng(3))
    altered = rows[:420] + [replace(p, outcome=(p.outcome + 1) % 3) for p in rows[420:]]

    original = recalibrate(BacktestResult(rows), min_history=300).predictions
    changed = recalibrate(BacktestResult(altered), min_history=300).predictions

    assert [p.model for p in original[:420]] == [p.model for p in changed[:420]]


def test_blend_trusts_an_informative_model_and_ignores_noise() -> None:
    rng = np.random.default_rng(4)
    truth = rng.dirichlet([3, 2, 2], size=3000)
    happened = np.array([rng.choice(3, p=p) for p in truth])
    noisy_market = truth * rng.lognormal(0, 0.6, truth.shape)
    noisy_market /= noisy_market.sum(axis=1, keepdims=True)
    pure_noise = rng.dirichlet([1, 1, 1], size=3000)

    informative = _fit_blend(np.log(noisy_market), np.log(truth), happened)
    useless = _fit_blend(np.log(truth), np.log(pure_noise), happened)

    assert informative[1] > informative[0]
    assert abs(useless[1]) < 0.1
