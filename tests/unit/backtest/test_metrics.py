import math

import numpy as np
import pytest

from edgeforge.backtest.metrics import (
    brier,
    calibration,
    expected_calibration_error,
    log_loss,
    ranked_probability_score,
    wilson_interval,
)


def test_log_loss_and_brier_known_values() -> None:
    probs = np.array([[0.5, 0.3, 0.2], [0.2, 0.2, 0.6]])
    outcome = np.array([0, 2])

    assert log_loss(probs, outcome) == pytest.approx(-(math.log(0.5) + math.log(0.6)) / 2)
    assert brier(probs, outcome) == pytest.approx(((0.25 + 0.09 + 0.04) + (0.04 + 0.04 + 0.16)) / 2)


def test_uniform_three_way_log_loss_is_ln3() -> None:
    probs = np.full((4, 3), 1 / 3)

    assert log_loss(probs, np.array([0, 1, 2, 0])) == pytest.approx(math.log(3))


def test_log_loss_survives_zero_probability() -> None:
    assert math.isfinite(log_loss(np.array([[1.0, 0.0]]), np.array([1])))


def test_rps_penalises_distant_misses_more() -> None:
    home_heavy = np.array([[0.8, 0.15, 0.05]])

    near = ranked_probability_score(home_heavy, np.array([1]))
    far = ranked_probability_score(home_heavy, np.array([2]))
    perfect = ranked_probability_score(np.array([[1.0, 0.0, 0.0]]), np.array([0]))

    assert far > near > perfect == 0.0


def test_calibration_of_perfectly_calibrated_predictions() -> None:
    rng = np.random.default_rng(0)
    predicted = rng.uniform(0, 1, 20_000)
    happened = rng.uniform(0, 1, 20_000) < predicted

    table = calibration(predicted, happened, bins=10)

    assert len(table) == 10
    assert sum(b.count for b in table) == 20_000
    assert expected_calibration_error(table) < 0.02
    assert all(b.observed_low <= b.observed <= b.observed_high for b in table)


def test_calibration_detects_overconfidence() -> None:
    predicted = np.full(1000, 0.8)
    happened = np.arange(1000) < 600

    [only_bin] = calibration(predicted, happened)

    assert only_bin.observed == pytest.approx(0.6)
    assert expected_calibration_error([only_bin]) == pytest.approx(0.2)


def test_wilson_interval() -> None:
    low, high = wilson_interval(70, 100)

    assert low < 0.7 < high
    assert (low, high) == pytest.approx((0.604, 0.781), abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)
