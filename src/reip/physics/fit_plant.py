"""Calibrate the PV plant model to each site's observed output envelope.

GEFCom2014 hid this problem by publishing power already normalised to [0, 1]. Real SCADA
does not, and a generic PV model turns out to be a poor description of any particular
plant. Three things vary per site and none are in any public registry:

* **Mounting.** A horizontal single-axis tracker produces a wide flat-topped day; a fixed
  array produces a narrow bell. Model the wrong one and morning output is out by several
  fold.
* **DC oversizing.** Utility plants install far more DC panel than AC inverter - ratios of
  1.2 to over 2.0 - so they hit their export limit mid-morning and hold it for hours. The
  flat top is the inverter clipping, not the sun.
* **Export limit.** The metered ceiling is often below nameplate.

Left uncalibrated these distort the *denominator* of the solar target. Avonlie is the
worked example: a generic fixed-tilt 1.2-ratio model puts clear-sky output at 16 MW in the
hour the plant is actually exporting its full 188 MW, so the clear-sky index reads 11.7
instead of about 1.0, and the target saturates against its cap on a sixth of all daylight
hours. The model then trains on a target that is mostly clipping artefact.

The fix is to fit the plant rather than assume it: grid-search mounting and DC/AC ratio so
the modelled clear-sky curve matches the plant's own high-output envelope. This uses only
training-period generation and no future information. For a genuinely new site with no
history the parameters come from its datasheet instead, so the cold-start path is
unaffected - it just needs two more numbers alongside capacity and coordinates.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from reip.physics.solar import clearsky_ac_mw
from reip.schemas import Mount, SiteMeta

log = logging.getLogger(__name__)

# Candidate grid. Ratios span the range seen in utility PV, from barely oversized to the
# heavily clipped designs common where connection capacity is the binding constraint.
DC_AC_RATIOS: tuple[float, ...] = (1.1, 1.25, 1.4, 1.6, 1.8, 2.1, 2.5)
MOUNTS: tuple[Mount, ...] = (Mount.FIXED, Mount.SINGLE_AXIS)

# The envelope is a high quantile of observed output per (month, hour) cell: what the
# plant achieves on its best days, which is what "clear sky" means operationally.
ENVELOPE_QUANTILE = 0.98
MIN_CELL_SAMPLES = 5


def observed_envelope(power_mw: pd.Series) -> pd.Series:
    """The plant's own best-case output by month and hour of day."""
    frame = pd.DataFrame({"power": power_mw.astype("float64")})
    index = pd.DatetimeIndex(power_mw.index)
    frame["month"] = index.month
    frame["hour"] = index.hour

    grouped = frame.groupby(["month", "hour"])["power"]
    envelope = grouped.quantile(ENVELOPE_QUANTILE)
    counts = grouped.size()
    envelope = envelope[counts >= MIN_CELL_SAMPLES]
    envelope.index.names = ["month", "hour"]
    return envelope


def _modelled_envelope(times: pd.DatetimeIndex, site: SiteMeta) -> pd.Series:
    modelled = clearsky_ac_mw(times, site)
    frame = pd.DataFrame({"power": modelled.to_numpy()}, index=times)
    out = frame.groupby([frame.index.month, frame.index.hour])["power"].max()
    out.index.names = ["month", "hour"]
    return out


def fit_site(power_mw: pd.Series, site: SiteMeta) -> tuple[SiteMeta, dict]:
    """Grid-search mounting and DC/AC ratio to match the plant's observed envelope.

    Scored on the envelope rather than hour-by-hour output because the target is a
    *clear-sky reference*: it should trace what the plant does on its best days, and it
    should not be dragged down by cloudy ones.
    """
    observed = observed_envelope(power_mw)
    if observed.empty or float(observed.max()) <= 0:
        return site, {"fitted": False, "reason": "no usable envelope"}

    # One representative year of hourly stamps is enough to trace the envelope, and keeps
    # the search cheap across a 14-candidate grid.
    times = pd.DatetimeIndex(power_mw.index)
    sample = times[:: max(1, len(times) // 8760)]

    best: tuple[float, Mount, float] | None = None
    for mount in MOUNTS:
        for ratio in DC_AC_RATIOS:
            candidate = site.model_copy(update={"mount": mount, "dc_ac_ratio": ratio})
            modelled = _modelled_envelope(sample, candidate)
            aligned = observed.align(modelled, join="inner")
            if aligned[0].empty:
                continue
            error = float(np.sqrt(np.mean((aligned[0] - aligned[1]) ** 2)))
            if best is None or error < best[0]:
                best = (error, mount, ratio)

    if best is None:
        return site, {"fitted": False, "reason": "no candidate aligned"}

    rmse, mount, ratio = best
    fitted = site.model_copy(update={"mount": mount, "dc_ac_ratio": ratio})
    return fitted, {
        "fitted": True,
        "mount": mount.value,
        "dc_ac_ratio": ratio,
        "envelope_rmse_mw": rmse,
        "envelope_rmse_pct_capacity": 100.0 * rmse / site.capacity_mw,
    }


def fit_all(power: pd.DataFrame, registry_path=None) -> dict[str, dict]:
    """Fit every solar site with generation data and write the parameters to the registry."""
    import yaml

    from reip.config import get_settings
    from reip.sites.registry import SiteRegistry

    registry_path = registry_path or get_settings().sites_file
    registry = SiteRegistry.load(registry_path)
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    by_id = {entry["site_id"]: entry for entry in raw["sites"]}

    results: dict[str, dict] = {}
    for site_id, block in power.groupby("site_id"):
        if site_id not in registry:
            continue
        series = block.set_index("valid_time_utc").sort_index()["power_mw"].astype("float64")
        fitted, diagnostics = fit_site(series, registry.get(str(site_id)))
        results[str(site_id)] = diagnostics
        if not diagnostics.get("fitted"):
            continue
        entry = by_id[str(site_id)]
        entry["mount"] = fitted.mount.value
        entry["dc_ac_ratio"] = round(fitted.dc_ac_ratio, 3)

    registry_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return results


if __name__ == "__main__":
    from reip.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    frame = pd.read_parquet(get_settings().data_canonical / "aemo_solar_power.parquet")
    fits = fit_all(frame)

    ok = {k: v for k, v in fits.items() if v.get("fitted")}
    print(f"fitted {len(ok)}/{len(fits)} sites")
    tracked = sum(1 for v in ok.values() if v["mount"] == "single_axis")
    print(f"  single-axis tracking: {tracked}   fixed: {len(ok) - tracked}")
    if ok:
        ratios = [v["dc_ac_ratio"] for v in ok.values()]
        errors = [v["envelope_rmse_pct_capacity"] for v in ok.values()]
        print(f"  DC/AC ratio: median {np.median(ratios):.2f}, range {min(ratios)}-{max(ratios)}")
        print(f"  envelope RMSE: median {np.median(errors):.1f}% of capacity")
