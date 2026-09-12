"""Forecast metrics.

Errors are normalised by installed capacity, not by mean output. Normalising by the mean
flatters solar enormously - half the rows are night, the mean is small, and dividing by it
inflates every score. Capacity is the denominator the industry uses and the one a grid
operator can interpret: "3% of nameplate" means something, "12% of average output" does not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from reip.schemas import LEAD_BUCKETS


def nmae(y_true: np.ndarray, y_pred: np.ndarray, capacity: np.ndarray) -> float:
    """Mean absolute error as a percentage of installed capacity."""
    return float(100.0 * np.mean(np.abs(y_true - y_pred) / capacity))


def nrmse(y_true: np.ndarray, y_pred: np.ndarray, capacity: np.ndarray) -> float:
    """Root mean squared error as a percentage of installed capacity."""
    return float(100.0 * np.sqrt(np.mean(((y_true - y_pred) / capacity) ** 2)))


def mbe(y_true: np.ndarray, y_pred: np.ndarray, capacity: np.ndarray) -> float:
    """Mean bias error, percent of capacity. Sign matters: positive means under-forecasting.

    Reported separately from MAE because a model can have excellent MAE and a systematic
    bias, and for grid operations a persistent one-directional error is a different and
    more damaging problem than symmetric noise.
    """
    return float(100.0 * np.mean((y_true - y_pred) / capacity))


def r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def pinball(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    delta = y_true - y_pred
    return float(np.mean(np.maximum(alpha * delta, (alpha - 1.0) * delta)))


def picp(y_true: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    """Prediction Interval Coverage Probability, percent.

    The honesty check on the uncertainty band. A p10-p90 interval should contain the truth
    about 80% of the time. Much below and the model is overconfident - the band is
    decoration rather than information. Much above and it is uselessly wide.
    """
    return float(100.0 * np.mean((y_true >= lower) & (y_true <= upper)))


def interval_width(lower: np.ndarray, upper: np.ndarray, capacity: np.ndarray) -> float:
    """Mean p10-p90 width as a percentage of capacity. Read alongside PICP, never alone."""
    return float(100.0 * np.mean((upper - lower) / capacity))


def skill_score(model_error: float, reference_error: float) -> float:
    """Fractional error reduction against a reference, percent.

    Positive means the model beats the reference. This, not a raw error, is the headline:
    an nMAE of 6% is meaningless until you know that the obvious baseline scores 11%.
    """
    if reference_error <= 0:
        return float("nan")
    return float(100.0 * (1.0 - model_error / reference_error))


def evaluate_predictions(
    frame: pd.DataFrame,
    *,
    truth_col: str = "actual_mw",
    pred_col: str = "p50_mw",
    capacity_col: str = "capacity_mw",
    lower_col: str | None = None,
    upper_col: str | None = None,
) -> dict[str, float]:
    """All deterministic metrics for one prediction column, plus interval metrics if given."""
    y = frame[truth_col].to_numpy(dtype="float64")
    p = frame[pred_col].to_numpy(dtype="float64")
    cap = frame[capacity_col].to_numpy(dtype="float64")

    out = {
        "n": float(len(frame)),
        "nmae_pct": nmae(y, p, cap),
        "nrmse_pct": nrmse(y, p, cap),
        "mbe_pct": mbe(y, p, cap),
        "r2": r_squared(y, p),
    }
    if lower_col and upper_col:
        lo = frame[lower_col].to_numpy(dtype="float64")
        hi = frame[upper_col].to_numpy(dtype="float64")
        out["picp_pct"] = picp(y, lo, hi)
        out["interval_width_pct"] = interval_width(lo, hi, cap)
    return out


def by_lead_bucket(frame: pd.DataFrame, pred_col: str, **kwargs: str | None) -> pd.DataFrame:
    """Metrics split by forecast lead time.

    The whole point of the evaluation. One pooled number conceals how skill decays, which
    is the single thing an operator planning 72 hours out needs to know.
    """
    rows = []
    for label, lo, hi in LEAD_BUCKETS:
        window = frame[(frame["horizon_h"] >= lo) & (frame["horizon_h"] <= hi)]
        if window.empty:
            continue
        rows.append(
            {"lead_bucket": label, **evaluate_predictions(window, pred_col=pred_col, **kwargs)}
        )
    rows.append({"lead_bucket": "all", **evaluate_predictions(frame, pred_col=pred_col, **kwargs)})
    return pd.DataFrame(rows)
