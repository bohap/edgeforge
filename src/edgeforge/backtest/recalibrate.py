"""Walk-forward recalibration of backtest predictions.

Each prediction is recalibrated with a calibrator fitted only on earlier predictions of the
same market whose matches had finished at least ``settle_delay`` before it was made, and the
calibrator is refitted every ``refit_every``. No prediction ever sees its own or later
results.
"""

from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np

from edgeforge.backtest.walk_forward import MARKETS, BacktestResult, Prediction
from edgeforge.models.calibration import PowerCalibrator, fit_power_calibrator


def recalibrate(
    result: BacktestResult,
    *,
    min_history: int = 300,
    refit_every: timedelta = timedelta(days=28),
    settle_delay: timedelta = timedelta(days=1),
) -> BacktestResult:
    """Return a copy of ``result`` with calibrated model probabilities.

    Predictions made before ``min_history`` settled predictions exist are left unchanged.
    """
    calibrated: list[Prediction] = []
    for code, _, _outcomes in MARKETS:
        rows = sorted((p for p in result.predictions if p.market == code), key=lambda p: p.as_of)
        calibrator: PowerCalibrator | None = None
        fitted_at: datetime | None = None
        for p in rows:
            if fitted_at is None or p.as_of - fitted_at >= refit_every:
                history = [h for h in rows if h.as_of + settle_delay <= p.as_of]
                if len(history) >= min_history:
                    calibrator = fit_power_calibrator(
                        np.array([h.model for h in history]),
                        np.array([h.outcome for h in history]),
                    )
                    fitted_at = p.as_of
            if calibrator is None:
                calibrated.append(p)
                continue
            probs = calibrator.apply(np.array(p.model))
            calibrated.append(replace(p, model=tuple(float(x) for x in probs)))
    return BacktestResult(predictions=calibrated)
