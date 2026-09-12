"""Regional scenarios by historical residual resampling.

The models emit a marginal distribution per site per hour. Everything Phase 2 does needs a
*joint* one, for two reasons that fail differently.

**Aggregation.** Adding up per-site p10 values assumes every plant's forecast error moves
together. Measured on the residual store, mean pairwise correlation between plants in a
region is about +0.12 to +0.23 - positive, and nothing like 1. Verified against outcomes,
the naive quantile sum covers 99-100% of hours against a nominal 80%, at up to 3.5x the
width it needs. An operator sizing reserve from that lower bound would procure for a
shortfall the fleet does not have.

**Dispatch.** A battery's state of charge at hour 30 depends on what happened in hours
1-29. Quantiles describe hours in isolation and cannot express a trajectory, so there is
nothing coherent for a dispatch optimiser to plan against.

Each scenario is therefore the median forecast plus one **real historical error field**,
taken as a contiguous block across every site at once:

    scenario[i, hour, site] = p50[hour, site] + residual[block_i, hour, site] * capacity

Because the block is a genuine slice of history, the errors within it already carry the
cross-site and hour-to-hour dependence the atmosphere actually produced. Nothing is
assumed about correlation and no correlation matrix is fitted.

**Why not the Schaake shuffle over the model's own quantiles.** That was the first design:
sample each marginal at N probability levels, then permute to match a historical rank
pattern. It preserves the calibrated marginals exactly and is the textbook method. It also
failed verification badly - regional coverage of 28% against a nominal 80% for solar.

The reason is worth recording. Reconstructing a full distribution from p10/p50/p90 needs a
tail model, and 20% of scenarios land beyond those points. Solar's error distribution is
heavy-tailed: per-site intervals cover 91.5% of outcomes, comfortably wide for a typical
hour, while the standard deviation of the same errors is 1.7x what those intervals imply,
because it is carried by the 8.5% that escape. Coverage and variance are different
properties, aggregation is a variance operation, and no three-point interpolation recovers
the difference. Resampling residuals sidesteps the reconstruction entirely - the historical
field already has the right shape, the right variance and the right dependence, all
measured.

What is given up is conditional heteroscedasticity: the model knows a cloudy afternoon is
less predictable than a clear one, and a uniformly drawn block does not. `dispersion`
restores that on average; see `generate_from_arrays`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from reip.portfolio import residuals as residual_store
from reip.schemas import SiteForecast, Tech

log = logging.getLogger(__name__)

DEFAULT_SCENARIOS: int = 200

# Quantile levels the models emit, and the levels reported back for a region.
MODEL_LEVELS: tuple[float, float, float] = (0.10, 0.50, 0.90)


@dataclass(frozen=True)
class ScenarioSet:
    """N coherent futures for one region.

    `values` is `(scenario, hour, site)` in MW. The scenario axis has no meaning of its own -
    scenario 0 is not "the low case" - because each is an equally likely draw. Anything
    resembling a quantile must be recomputed across that axis, which is what `quantiles`
    does.
    """

    values: np.ndarray
    site_ids: list[str]
    valid_times: pd.DatetimeIndex
    horizons: np.ndarray

    @property
    def n_scenarios(self) -> int:
        return self.values.shape[0]

    def regional_total(self) -> np.ndarray:
        """Sum across sites: `(scenario, hour)` in MW.

        This is the whole point. Summing *inside* a scenario is correct, because every site
        in it belongs to one coherent future. Summing per-site quantiles across sites is
        not, because it silently assumes those futures coincide.
        """
        return self.values.sum(axis=2)

    def quantiles(self, levels: tuple[float, ...] = MODEL_LEVELS) -> pd.DataFrame:
        """Regional quantiles recovered from the ensemble, one row per hour."""
        total = self.regional_total()
        frame = pd.DataFrame({"valid_time_utc": self.valid_times, "horizon_h": self.horizons})
        for level in levels:
            frame[f"p{int(level * 100):02d}_mw"] = np.quantile(total, level, axis=0)
        frame["mean_mw"] = total.mean(axis=0)
        return frame

    def naive_quantile_sum(self, marginals: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """What summing per-site quantiles would have said - kept so the gap is showable.

        Not a fallback. It exists to be plotted against `quantiles()`, because the case for
        this module is quantitative and should be presented as such rather than asserted.
        """
        frame = pd.DataFrame({"valid_time_utc": self.valid_times, "horizon_h": self.horizons})
        for column in ("p10_mw", "p50_mw", "p90_mw"):
            frame[column] = sum(marginals[s][column].to_numpy() for s in self.site_ids)
        return frame


DISPERSION_FILE = "scenario_dispersion.json"


def load_dispersion(tech: Tech) -> float:
    """The fitted dispersion factor for a technology, or 1.0 if none has been fitted."""
    import json

    from reip.config import get_settings

    path = get_settings().artifacts_dir / DISPERSION_FILE
    if not path.exists():
        log.warning("no %s; scenarios will be uncalibrated (dispersion 1.0)", DISPERSION_FILE)
        return 1.0
    return float(json.loads(path.read_text(encoding="utf-8")).get(tech.value, 1.0))


def generate(
    forecasts: dict[str, SiteForecast],
    tech: Tech,
    *,
    n_scenarios: int = DEFAULT_SCENARIOS,
    seed: int = 42,
    store: pd.DataFrame | None = None,
    dispersion: float | None = None,
) -> ScenarioSet:
    """Build a coherent scenario ensemble from per-site `SiteForecast` objects."""
    dispersion = load_dispersion(tech) if dispersion is None else dispersion
    if not forecasts:
        raise ValueError("no forecasts supplied")

    site_ids = sorted(forecasts)
    frames = {s: forecasts[s].to_frame() for s in site_ids}

    reference = frames[site_ids[0]]
    n_hours = len(reference)
    for s, frame in frames.items():
        if len(frame) != n_hours:
            raise ValueError(f"{s} has {len(frame)} hours, expected {n_hours}")

    stack = lambda column: np.column_stack(  # noqa: E731 - local shorthand, used three times
        [frames[s][column].to_numpy(dtype="float64") for s in site_ids]
    )
    return generate_from_arrays(
        dispersion=dispersion,
        p10=stack("p10_mw"),
        p50=stack("p50_mw"),
        p90=stack("p90_mw"),
        capacities=np.array([forecasts[s].capacity_mw for s in site_ids], dtype="float64"),
        site_ids=site_ids,
        valid_times=pd.DatetimeIndex(reference["valid_time_utc"]),
        horizons=reference["horizon_h"].to_numpy(dtype="int16"),
        tech=tech,
        n_scenarios=n_scenarios,
        seed=seed,
        store=store,
    )


def generate_from_arrays(
    *,
    p10: np.ndarray,  # noqa: ARG001 - retained for API symmetry; see the note on spread
    p50: np.ndarray,
    p90: np.ndarray,  # noqa: ARG001
    capacities: np.ndarray,
    site_ids: list[str],
    valid_times: pd.DatetimeIndex,
    horizons: np.ndarray,
    tech: Tech,
    n_scenarios: int = DEFAULT_SCENARIOS,
    seed: int = 42,
    store: pd.DataFrame | None = None,
    dispersion: float = 1.0,
) -> ScenarioSet:
    """The shuffle itself, on `(hour, site)` quantile arrays.

    Separate from `generate` so verification can run on historical blocks, which a
    `SiteForecast` cannot represent: it requires strictly increasing horizons, whereas a
    historical window is many hours at one fixed lead.
    """
    n_hours = len(valid_times)
    store = residual_store.load(tech) if store is None else store
    blocks = residual_store.template_blocks(
        store, site_ids, n_hours, start_hour=int(pd.DatetimeIndex(valid_times)[0].hour)
    )

    rng = np.random.default_rng(seed)
    replace = len(blocks) < n_scenarios
    if replace:
        log.warning(
            "only %d template blocks for %d scenarios; sampling with replacement, which "
            "duplicates error patterns and understates ensemble diversity",
            len(blocks),
            n_scenarios,
        )
    chosen = blocks[rng.choice(len(blocks), size=n_scenarios, replace=replace)]

    # Sites absent from the store have no history to draw on. Give them zero perturbation
    # rather than an invented one: the median forecast is the honest answer for a plant
    # nothing is known about, and pretending otherwise would put fabricated spread into a
    # regional total.
    known = [s in store.columns for s in site_ids]
    if not all(known):
        missing = [s for s, ok in zip(site_ids, known, strict=True) if not ok]
        log.info(
            "%d of %d sites absent from the residual store, carried at p50 with no spread: %s",
            len(missing), len(site_ids), missing[:5],
        )
        padded = np.zeros((n_scenarios, n_hours, len(site_ids)), dtype="float64")
        k = 0
        for j, ok in enumerate(known):
            if ok:
                padded[:, :, j] = chosen[:, :, k]
                k += 1
        chosen = padded

    # Each scenario is the median forecast plus one real historical error field, rescaled
    # from per-unit back into megawatts.
    #
    # `dispersion` corrects one known shortcoming. Blocks are drawn uniformly from history,
    # so every window gets the average amount of forecast error regardless of whether the
    # weather it describes is calm or violent. Real error is conditional: a wind ramp is
    # far less predictable than a settled airstream. Averaged over many windows that shows
    # up as systematic under-coverage - measured at 66% against a nominal 80% for wind
    # before this factor, and the overconfident direction is the one that matters, because
    # the balance module reads the lower bound as firm capacity.
    #
    # A single scalar per technology cannot recover the conditional structure; it restores
    # the average. Fitted out of sample by `eval/scenarios.calibrate`.
    values = p50[None, :, :] + dispersion * chosen * capacities[None, None, :]
    values = np.clip(values, 0.0, capacities[None, None, :])

    return ScenarioSet(
        values=values,
        site_ids=list(site_ids),
        valid_times=pd.DatetimeIndex(valid_times),
        horizons=np.asarray(horizons, dtype="int16"),
    )


def rank_histogram(observed: np.ndarray, ensemble: np.ndarray, bins: int | None = None) -> np.ndarray:
    """Where the observation falls within the sorted ensemble, counted per bin.

    A flat histogram means the ensemble is calibrated. A U shape means it is too narrow -
    reality keeps landing outside it. A dome means it is too wide. This is the check that
    the copula step did not quietly break the marginals it was supposed to preserve.
    """
    n = ensemble.shape[0]
    bins = bins or min(n + 1, 21)
    rank = (ensemble < observed[None, :]).sum(axis=0)
    return np.histogram(rank, bins=bins, range=(0, n))[0]
