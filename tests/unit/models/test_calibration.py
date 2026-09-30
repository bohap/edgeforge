import numpy as np
import pytest

from edgeforge.backtest.metrics import log_loss
from edgeforge.models.calibration import PowerCalibrator, fit_power_calibrator


def _overconfident(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """True probabilities, reported squared-and-renormalised (too extreme)."""
    truth = rng.dirichlet([3, 2, 2], size=n)
    outcome = np.array([rng.choice(3, p=p) for p in truth])
    reported = truth**2
    reported /= reported.sum(axis=1, keepdims=True)
    return reported, outcome


def test_identity_changes_nothing() -> None:
    probs = np.array([[0.5, 0.3, 0.2], [0.1, 0.2, 0.7]])

    assert PowerCalibrator.identity(3).apply(probs) == pytest.approx(probs)


def test_fitting_corrects_overconfidence() -> None:
    rng = np.random.default_rng(0)
    probs, outcome = _overconfident(rng, 4000)

    calibrator = fit_power_calibrator(probs, outcome)
    fixed = calibrator.apply(probs)

    assert calibrator.power == pytest.approx(0.5, abs=0.1)
    assert log_loss(fixed, outcome) < log_loss(probs, outcome) - 0.02
    assert fixed.sum(axis=1) == pytest.approx(np.ones(len(fixed)))


def test_well_calibrated_input_stays_close_to_identity() -> None:
    rng = np.random.default_rng(1)
    truth = rng.dirichlet([3, 2, 2], size=4000)
    outcome = np.array([rng.choice(3, p=p) for p in truth])

    calibrator = fit_power_calibrator(truth, outcome)

    assert calibrator.power == pytest.approx(1.0, abs=0.1)
    assert max(abs(b) for b in calibrator.bias) < 0.1


def test_empty_history_gives_identity() -> None:
    assert fit_power_calibrator(np.zeros((0, 2)), np.zeros(0, dtype=int)) == PowerCalibrator(
        1.0, (0.0, 0.0)
    )
