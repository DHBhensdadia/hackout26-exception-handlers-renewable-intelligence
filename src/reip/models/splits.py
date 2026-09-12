"""The 70-10-20 split, and the calibration that makes the uncertainty band honest.

Two ideas, both aimed at the same thing: a number that survives contact with data the
model has never seen.

**The split is site-disjoint, not just time-ordered.**

A plain chronological 70-10-20 answers "can this model predict next month at a plant it
already knows?" That is not the deployment question. `/forecast` takes an arbitrary
latitude and longitude, and Charanka has no generation history at all, so the honest test
holds out whole *plants*:

    test  = 20% of SITES, entirely unseen - never in train or validation
    train = first 87.5% of TIME at the remaining sites  (~70% of all rows)
    val   = last  12.5% of TIME at the remaining sites  (~10% of all rows)

Both dimensions are cut: the test sites are spatially unseen, and the validation block is
temporally after the training block, so nothing leaks in either direction. This is
deliberately harsher than a chronological split - scores will look worse than the 6.92%
solar figure a time-only holdout produced, and that is the point.

**Conformalised quantile regression fixes the band.**

Independently-fitted quantile models are not calibrated: wind's p10-p90 interval covered
only 71.8% of outcomes against a nominal 80%, meaning the band was too narrow and the
forecast quietly overconfident. That matters because Phase 2's shortage logic reads p10
directly - an interval that under-covers understates shortage risk.

CQR corrects it with a distribution-free guarantee. On the validation set - never used to
fit the trees - compute the conformity score

    E_i = max(q_lo(x_i) - y_i,  y_i - q_hi(x_i))

and take its (1-alpha) empirical quantile Q. Widening the interval to [q_lo - Q, q_hi + Q]
gives marginal coverage of at least 1-alpha on exchangeable data, whatever the underlying
model does. One scalar per technology, stored in the artifact and applied at predict time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Fraction of sites reserved as the spatially-unseen test set.
TEST_SITE_FRACTION = 0.20
# Of the remaining (train+val) rows, the share used for validation, taken from the end of
# the timeline so validation always follows training.
VAL_TIME_FRACTION = 0.125

# Nominal coverage of the p10-p90 interval.
TARGET_COVERAGE = 0.80


# Sites reserved purely to calibrate the uncertainty band. Carved out of the training
# sites, never fitted on. See `calib` in SplitMasks for why this has to be site-disjoint.
CALIB_SITE_FRACTION = 0.10


@dataclass(frozen=True)
class SplitMasks:
    """Boolean row masks for the partitions, plus what defines them.

    Four groups, not three, and the fourth is the one that makes the uncertainty band
    honest:

    * `train`    - 70% of sites, earlier time. Fits the trees.
    * `val`      - the same 70% of sites, later time. Early stopping only.
    * `calib`    - 10% of sites, held out entirely. Conformal calibration only.
    * `test`     - 20% of sites, held out entirely. Final score, touched once.

    The first attempt calibrated on `val` and it did not work: wind's validation coverage
    was already 80.2%, so the correction was nil, yet coverage on unseen sites was 72.5%.
    CQR's guarantee holds for *exchangeable* data, and a later hour at a plant the model
    knows is not exchangeable with a plant it has never seen - the second carries strictly
    more uncertainty. Calibrating on held-out sites makes the calibration set and the test
    set the same kind of thing, so the correction transfers.
    """

    train: np.ndarray
    val: np.ndarray
    calib: np.ndarray
    test: np.ndarray
    test_sites: list[str]
    calib_sites: list[str]
    val_cutoff: pd.Timestamp

    def summary(self, total: int) -> dict:
        return {
            "train_rows": int(self.train.sum()),
            "val_rows": int(self.val.sum()),
            "calib_rows": int(self.calib.sum()),
            "test_rows": int(self.test.sum()),
            "train_pct": round(100 * self.train.sum() / total, 1),
            "val_pct": round(100 * self.val.sum() / total, 1),
            "calib_pct": round(100 * self.calib.sum() / total, 1),
            "test_pct": round(100 * self.test.sum() / total, 1),
            "test_sites": self.test_sites,
            "calib_sites": self.calib_sites,
            "val_starts": str(self.val_cutoff),
        }


def make_split(
    site_id: pd.Series,
    valid_time: pd.Series,
    *,
    test_site_fraction: float = TEST_SITE_FRACTION,
    val_time_fraction: float = VAL_TIME_FRACTION,
    seed: int = 42,
) -> SplitMasks:
    """Build site-disjoint test and time-ordered train/validation masks.

    Test sites are chosen by a seeded shuffle rather than by capacity or data volume, so
    the held-out set is not accidentally all small plants or all one state - either would
    make the headline number unrepresentative.
    """
    sites = np.array(sorted(site_id.unique()))
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(sites))

    n_test = max(1, int(round(len(sites) * test_site_fraction)))
    n_calib = max(1, int(round(len(sites) * CALIB_SITE_FRACTION)))
    test_sites = sorted(sites[order[:n_test]].tolist())
    calib_sites = sorted(sites[order[n_test : n_test + n_calib]].tolist())

    ids = site_id.to_numpy()
    test = np.isin(ids, test_sites)
    calib = np.isin(ids, calib_sites)

    times = pd.DatetimeIndex(valid_time)
    fitting = ~(test | calib)
    if not fitting.any():
        raise ValueError("no rows left after reserving test and calibration sites")

    # The validation cutoff is a time, computed only over the fitting rows, so every
    # validation row is strictly later than every training row at the same site.
    kept = times[fitting]
    cutoff = kept.min() + (kept.max() - kept.min()) * (1.0 - val_time_fraction)
    later = np.asarray(times > cutoff)

    val = fitting & later
    train = fitting & ~later

    log.info(
        "split: train %s / val %s / calib %s / test %s rows | %d calib + %d test sites held out entirely",
        f"{int(train.sum()):,}",
        f"{int(val.sum()):,}",
        f"{int(calib.sum()):,}",
        f"{int(test.sum()):,}",
        len(calib_sites),
        len(test_sites),
    )
    return SplitMasks(
        train=train,
        val=val,
        calib=calib,
        test=test,
        test_sites=test_sites,
        calib_sites=calib_sites,
        val_cutoff=cutoff,
    )


def conformal_widening(
    y_true: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    *,
    coverage: float = TARGET_COVERAGE,
) -> float:
    """The CQR adjustment that brings empirical coverage up to `coverage`.

    Returns the amount to subtract from the lower quantile and add to the upper, in target
    units. A negative value means the interval was too wide and gets tightened - the
    method corrects in both directions, so an over-cautious band is narrowed just as an
    overconfident one is widened.
    """
    if len(y_true) == 0:
        return 0.0

    scores = np.maximum(lower - y_true, y_true - upper)
    n = len(scores)
    # Finite-sample correction: the (1-a)(n+1)/n empirical quantile is what carries the
    # coverage guarantee, not the plain (1-a) quantile.
    level = min(1.0, np.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method="higher"))


# Below this many calibration rows a bucket's own quantile is noise, and a noisy widening
# is worse than a pooled one: it would hand a lead bucket an interval calibrated on an
# accident. Such buckets inherit the pooled value instead.
MIN_BUCKET_SAMPLES: int = 500


def conformal_widening_by_bucket(
    y_true: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    horizon_h: np.ndarray,
    *,
    coverage: float = TARGET_COVERAGE,
) -> dict[str, float]:
    """One widening per lead bucket, plus a pooled fallback under `"all"`.

    A single scalar across 1-72 h is the wrong shape for this correction. Forecast error
    grows with lead time - a 72 h NWP carries roughly twice the error of a 24 h one - so a
    pooled widening is simultaneously too generous at short leads and too mean at long
    ones. Since it is fitted to hit 80% *on average*, it lands near 80% overall while
    over-covering the near term and under-covering exactly where uncertainty is largest.

    That matters beyond tidiness: everything downstream reads band width as a measure of
    how much reserve to hold, so a band that does not grow with horizon understates risk
    precisely at the horizons where risk is greatest.

    The `"all"` entry is always present. It is what a bucket with too little data falls back
    to, and what a caller uses when a horizon lands outside the defined buckets.
    """
    from reip.schemas import lead_bucket

    widenings = {"all": conformal_widening(y_true, lower, upper, coverage=coverage)}

    buckets = np.array([lead_bucket(int(h)) for h in horizon_h])
    for label in np.unique(buckets):
        if label == "out-of-range":
            continue
        mask = buckets == label
        n = int(mask.sum())
        if n < MIN_BUCKET_SAMPLES:
            log.info("bucket %s has only %d calibration rows; using pooled widening", label, n)
            continue
        widenings[str(label)] = conformal_widening(
            y_true[mask], lower[mask], upper[mask], coverage=coverage
        )
    return widenings


def widening_for(widenings: dict[str, float] | float, horizon_h: np.ndarray) -> np.ndarray:
    """Per-row widening, looked up by each row's lead bucket.

    Accepts a bare float so artifacts trained before calibration became bucket-aware keep
    loading and keep predicting - they simply apply one value everywhere, which is what
    they were calibrated to do.
    """
    from reip.schemas import lead_bucket

    if not isinstance(widenings, dict):
        return np.full(len(horizon_h), float(widenings), dtype="float64")

    fallback = float(widenings.get("all", 0.0))
    return np.array(
        [float(widenings.get(lead_bucket(int(h)), fallback)) for h in horizon_h],
        dtype="float64",
    )


def apply_conformal(
    lower: np.ndarray,
    upper: np.ndarray,
    widening: float | np.ndarray,
    *,
    floor: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Widen (or tighten) a predicted interval by the calibrated amount.

    `widening` may be a scalar or one value per row, so a bucket-aware correction applies
    through the same path as a pooled one.
    """
    adjusted_lower = np.maximum(lower - widening, floor)
    adjusted_upper = np.maximum(upper + widening, adjusted_lower)
    return adjusted_lower, adjusted_upper


def empirical_coverage(y_true: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    if len(y_true) == 0:
        return float("nan")
    return float(np.mean((y_true >= lower) & (y_true <= upper)))
