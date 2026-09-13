"""Reliability calibration for the surplus and shortage probabilities.

The raw ensemble frequencies are sharp but not reliable. Measured on held-out hours, SA1
shortage probabilities of 0.29 were followed by shortage 86% of the time, and 0.49 by 98%.
Under-confident, and in the direction that matters: a control room told there is a 30%
chance of being short prepares differently from one told 86%.

The cause is conditional bias, not spread. The ensemble is centred on the p50 forecast, and
in precisely the hours that end in shortage - low wind, high load - that forecast runs
optimistic. A wider band does not fix a centre that is in the wrong place for a particular
kind of hour.

What does fix it, without a better model, is mapping predicted frequency onto observed
frequency: an isotonic regression fitted on one stretch of history and applied to the next.
Isotonic rather than a parametric curve because the only thing that should be assumed is
monotonicity - a higher ensemble frequency ought to mean a higher real chance, and nothing
beyond that is known about the shape.

This does not make the underlying forecast better; it makes the number honest about how
good it is. Spec section 26 asks for exactly that.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from reip.config import get_settings

log = logging.getLogger(__name__)

CALIBRATION_FILE = "balance_calibration.json"

# Below this many observations an event has no reliable frequency to fit against, and an
# isotonic fit would simply memorise noise.
MIN_SAMPLES: int = 200


def fit(probabilities: np.ndarray, outcomes: np.ndarray) -> dict:
    """Fit a monotone map from predicted probability to observed frequency.

    Returned as breakpoints rather than a fitted object so applying it needs nothing but
    `numpy.interp` - no scikit-learn at serve time, and the mapping is inspectable in the
    artifact instead of being opaque.
    """
    if len(probabilities) < MIN_SAMPLES:
        log.warning("only %d samples; identity calibration kept", len(probabilities))
        return {"x": [0.0, 1.0], "y": [0.0, 1.0], "n": int(len(probabilities))}

    from sklearn.isotonic import IsotonicRegression

    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(probabilities, outcomes)

    grid = np.linspace(0.0, 1.0, 21)
    mapped = model.predict(grid)
    # Force the endpoints. An event the ensemble deems impossible should stay impossible,
    # and one it deems certain should stay certain; isotonic can otherwise pull both inward
    # and leave the calibrated probability unable to reach 0 or 1 at all.
    mapped[0], mapped[-1] = 0.0, 1.0
    mapped = np.maximum.accumulate(mapped)

    return {"x": grid.tolist(), "y": mapped.tolist(), "n": int(len(probabilities))}


def apply(probabilities: np.ndarray, mapping: dict | None) -> np.ndarray:
    """Map raw ensemble frequencies onto calibrated ones."""
    if not mapping:
        return probabilities
    return np.interp(probabilities, mapping["x"], mapping["y"])


def load(region: str, event: str, path: Path | None = None) -> dict | None:
    """The stored mapping for one region and event, or None if none was fitted."""
    path = path or (get_settings().artifacts_dir / CALIBRATION_FILE)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get(region, {}).get(event)


def save(mappings: dict, path: Path | None = None) -> Path:
    path = path or (get_settings().artifacts_dir / CALIBRATION_FILE)
    path.write_text(json.dumps(mappings, indent=2), encoding="utf-8")
    log.info("wrote %s", path)
    return path
