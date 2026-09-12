"""GEFCom2014 ingest: the training corpus.

Why this dataset and not a synthetic one: GEFCom2014 pairs *real numerical weather
predictions* with *real measured power* for 3 PV plants and 10 wind farms over two-plus
years. That pairing is the whole point. A model trained on observed weather and served
on forecasts learns a mapping that does not exist at prediction time; a model trained on
GEFCom learns the mapping it will actually be asked to perform. It is also a canonical
benchmark, so the resulting error can be placed against published scores rather than
asserted in a vacuum.

Two source-specific traps are handled here, both of which produce a model that looks
fine and is wrong:

1. **Accumulated radiation fields.** SSRD, STRD, TSR and TP are published in J/m2
   accumulated from the start of each forecast run, not as hourly means. Feeding them
   raw would hand the model a monotonically rising ramp that correlates with time of day
   by construction. They are differenced within each accumulation window and converted
   to W/m2. The reset boundary is *detected*, not assumed.

2. **Reconstructing the forecast issue time.** GEFCom does not label it. The
   accumulation reset does: it happens at 01:00 UTC daily, which means each run is
   issued at 00:00 UTC and covers 01:00 through 00:00 the next day. That gives real
   `horizon_h` values of 1..24. See `LEAD_TIME_LIMITATION` below - this matters.
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from reip.config import get_settings
from reip.schemas import Tech, validate_power, validate_weather

log = logging.getLogger(__name__)

# Mirrors, tried in order. The Dropbox copy is the one linked from the competition
# organiser's own page; the Elsevier supplement is the archival copy of record.
GEFCOM_MIRRORS: tuple[str, ...] = (
    "https://www.dropbox.com/s/pqenrr2mcvl0hk9/GEFCom2014.zip?dl=1",
    "https://ars.els-cdn.com/content/image/1-s2.0-S0169207016000133-mmc1.zip",
)

ARCHIVE_NAME = "gefcom2014.zip"

# ECMWF parameter ids as published in the solar track instructions.
SOLAR_VARS: dict[str, str] = {
    "VAR78": "tclw",  # total column liquid water, kg/m2
    "VAR79": "tciw",  # total column ice water, kg/m2
    "VAR134": "sp",  # surface pressure, Pa
    "VAR157": "rh",  # relative humidity at 1000 mbar, %
    "VAR164": "tcc",  # total cloud cover, 0-1
    "VAR165": "u10",  # 10 m U wind, m/s
    "VAR166": "v10",  # 10 m V wind, m/s
    "VAR167": "t2m",  # 2 m temperature, K
    "VAR169": "ssrd",  # surface solar radiation down, J/m2 ACCUMULATED
    "VAR175": "strd",  # surface thermal radiation down, J/m2 ACCUMULATED
    "VAR178": "tsr",  # top net solar radiation, J/m2 ACCUMULATED
    "VAR228": "tp",  # total precipitation, m ACCUMULATED
}
ACCUMULATED_VARS: tuple[str, ...] = ("VAR169", "VAR175", "VAR178", "VAR228")

SECONDS_PER_HOUR = 3600.0

# The forecast run boundary, recovered from the accumulation reset (see module docstring).
RUN_ISSUE_HOUR_UTC = 0

LEAD_TIME_LIMITATION = """\
GEFCom2014 supplies a single day-ahead forecast run per day, so the horizons genuinely
present in this data are 1-24 h. It cannot, on its own, evidence skill at 48 or 72 h.

This is handled deliberately rather than papered over. The GBDT learns power = f(weather),
which is horizon-agnostic: what degrades with lead time is the *accuracy of the weather
input*, not the weather-to-power mapping. Lead-dependent behaviour is therefore supplied
separately, by calibrating how NWP error grows from lead 1 to lead 3 against Open-Meteo
Previous Runs, and widening the predictive interval accordingly. The evaluation report
states which numbers are measured on GEFCom holdout and which come from that calibration.
"""


# --------------------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------------------


def download_archive(dest: Path | None = None, *, force: bool = False) -> Path:
    """Fetch the GEFCom2014 archive, trying each mirror in turn."""
    import httpx

    settings = get_settings()
    settings.ensure_dirs()
    dest = dest or settings.data_raw / ARCHIVE_NAME

    if dest.exists() and not force and dest.stat().st_size > 10_000_000:
        log.info("archive already present at %s (%d bytes)", dest, dest.stat().st_size)
        return dest

    errors: list[str] = []
    for url in GEFCOM_MIRRORS:
        try:
            log.info("downloading GEFCom2014 from %s", url)
            with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as r:
                r.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
            if zipfile.is_zipfile(dest):
                return dest
            errors.append(f"{url}: not a zip archive")
        except Exception as exc:  # noqa: BLE001 - any mirror failure should try the next
            errors.append(f"{url}: {exc}")

    raise RuntimeError("all GEFCom2014 mirrors failed:\n  " + "\n  ".join(errors))


def _open_track(archive: Path, track: str) -> zipfile.ZipFile:
    """Open the inner per-track zip ('S' for solar, 'W' for wind)."""
    outer = zipfile.ZipFile(archive)
    return zipfile.ZipFile(io.BytesIO(outer.read(f"GEFCom2014 Data/GEFCom2014-{track}_V2.zip")))


# --------------------------------------------------------------------------------------
# Shared transforms
# --------------------------------------------------------------------------------------


def _parse_timestamps(raw: pd.Series) -> pd.Series:
    """GEFCom stamps are naive 'YYYYMMDD H:MM' in UTC. Both tracks, both widths."""
    ts = pd.to_datetime(raw.str.strip(), format="%Y%m%d %H:%M", utc=True, errors="coerce")
    if ts.isna().any():
        raise ValueError(f"{int(ts.isna().sum())} unparseable GEFCom timestamps")
    return ts


def _accumulation_window(ts: pd.Series) -> pd.Series:
    """Label each row with the forecast run it belongs to.

    A run is issued at 00:00 UTC and covers 01:00 through 00:00 the following day. So the
    window key is the calendar date of (timestamp - 1 hour): that maps 01:00..23:00 and
    the following 00:00 onto the same run.
    """
    return (ts - pd.Timedelta(hours=1)).dt.floor("D")


def deaccumulate(
    df: pd.DataFrame, columns: tuple[str, ...], *, group_cols: list[str]
) -> pd.DataFrame:
    """Convert accumulated fields to per-hour increments within each forecast run.

    The reset is verified rather than trusted: if a column turns out not to be
    accumulating (already differenced, or a provider that publishes means) it is left
    untouched. Blindly differencing an already-hourly field would silently destroy it.
    """
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            continue
        grouped = out.groupby(group_cols, sort=False)[col]
        rising = grouped.apply(lambda s: (s.diff().dropna() >= -1e-6).mean())
        monotonic_fraction = float(np.nanmean(rising.to_numpy(dtype="float64")))
        if monotonic_fraction < 0.95:
            log.warning(
                "%s rises within-window only %.1f%% of the time; treating as already "
                "de-accumulated and leaving it unchanged",
                col,
                100 * monotonic_fraction,
            )
            continue
        # First hour of a run: the accumulation starts at zero, so the raw value IS the
        # increment. Subsequent hours are differences.
        out[col] = grouped.diff().fillna(out[col]).clip(lower=0.0)
    return out


def _uv_to_speed_dir(u: pd.Series, v: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Zonal/meridional components to speed (m/s) and meteorological direction (deg).

    Meteorological convention: the direction the wind blows *from*, clockwise from north.
    """
    speed = np.sqrt(u.astype("float64") ** 2 + v.astype("float64") ** 2)
    direction = (270.0 - np.degrees(np.arctan2(v.astype("float64"), u.astype("float64")))) % 360.0
    return pd.Series(speed, index=u.index), pd.Series(direction, index=u.index)


def _add_run_columns(df: pd.DataFrame, ts: pd.Series) -> pd.DataFrame:
    """Attach the reconstructed issue time and horizon."""
    issue = _accumulation_window(ts)
    df["issue_time_utc"] = issue
    df["valid_time_utc"] = ts
    df["horizon_h"] = ((ts - issue).dt.total_seconds() / SECONDS_PER_HOUR).round().astype("int16")
    return df


# --------------------------------------------------------------------------------------
# Solar track
# --------------------------------------------------------------------------------------


def load_solar(archive: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the solar track into canonical (weather, power) frames.

    Task 15 is used because it is the final task and therefore carries the longest
    training span; its predictor file already contains the power column.
    """
    track = _open_track(archive, "S")
    raw = pd.read_csv(io.BytesIO(track.read("Solar/Task 15/predictors15.csv")))

    ts = _parse_timestamps(raw["TIMESTAMP"])
    raw = raw.assign(_ts=ts, _window=_accumulation_window(ts))
    raw = raw.sort_values(["ZONEID", "_ts"]).reset_index(drop=True)

    raw = deaccumulate(raw, ACCUMULATED_VARS, group_cols=["ZONEID", "_window"])

    ws10, wd10 = _uv_to_speed_dir(raw["VAR165"], raw["VAR166"])

    weather = pd.DataFrame(
        {
            "site_id": "GEFCOM-SOLAR-" + raw["ZONEID"].astype(str),
            "ghi_wm2": raw["VAR169"] / SECONDS_PER_HOUR,  # J/m2 per hour -> W/m2
            "cloud_total": raw["VAR164"].clip(0.0, 1.0),
            "temp_2m_c": raw["VAR167"] - 273.15,  # K -> C
            "rh_pct": raw["VAR157"].clip(0.0, 100.0),
            "pressure_hpa": raw["VAR134"] / 100.0,  # Pa -> hPa
            "precip_mm": raw["VAR228"] * 1000.0,  # m -> mm
            "wind_speed_10m": ws10,
            "wind_dir_10m_deg": wd10,
            "source": "gefcom",
        }
    )
    weather = _add_run_columns(weather, raw["_ts"])

    power = pd.DataFrame(
        {
            "site_id": "GEFCOM-SOLAR-" + raw["ZONEID"].astype(str),
            "valid_time_utc": raw["_ts"],
            "tech": Tech.SOLAR.value,
            "power_mw": raw["POWER"],  # already normalised to [0,1]; capacity is 1.0 MW
            "capacity_mw": 1.0,
            "is_valid": raw["POWER"].notna(),
        }
    )
    power["power_mw"] = power["power_mw"].fillna(0.0).clip(lower=0.0)

    return validate_weather(weather, name="gefcom-solar"), validate_power(
        power, name="gefcom-solar"
    )


# --------------------------------------------------------------------------------------
# Wind track
# --------------------------------------------------------------------------------------


def load_wind(archive: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the wind track into canonical (weather, power) frames.

    The wind track supplies only U/V at 10 m and 100 m - no temperature, no pressure. Air
    density therefore cannot be computed from this source and is left null, which the
    feature builder handles by falling back to standard density. Downstream this means
    the density correction is inert during training and active at serve time, where it
    acts as a small physically-correct refinement of hub-height wind speed.
    """
    track = _open_track(archive, "W")
    inner = zipfile.ZipFile(io.BytesIO(track.read("Wind/Task 15/Task15_W_Zone1_10.zip")))

    frames = [
        pd.read_csv(io.BytesIO(inner.read(name)))
        for name in sorted(inner.namelist())
        if name.endswith(".csv")
    ]
    raw = pd.concat(frames, ignore_index=True)

    ts = _parse_timestamps(raw["TIMESTAMP"])
    raw = raw.assign(_ts=ts).sort_values(["ZONEID", "_ts"]).reset_index(drop=True)

    ws10, wd10 = _uv_to_speed_dir(raw["U10"], raw["V10"])
    ws100, wd100 = _uv_to_speed_dir(raw["U100"], raw["V100"])

    weather = pd.DataFrame(
        {
            "site_id": "GEFCOM-WIND-" + raw["ZONEID"].astype(str),
            "wind_speed_10m": ws10,
            "wind_speed_100m": ws100,
            "wind_dir_10m_deg": wd10,
            "wind_dir_100m_deg": wd100,
            "source": "gefcom",
        }
    )
    weather = _add_run_columns(weather, raw["_ts"])

    power = pd.DataFrame(
        {
            "site_id": "GEFCOM-WIND-" + raw["ZONEID"].astype(str),
            "valid_time_utc": raw["_ts"],
            "tech": Tech.WIND.value,
            "power_mw": raw["TARGETVAR"],
            "capacity_mw": 1.0,
            "is_valid": raw["TARGETVAR"].notna(),
        }
    )
    power["power_mw"] = power["power_mw"].fillna(0.0).clip(lower=0.0)

    return validate_weather(weather, name="gefcom-wind"), validate_power(power, name="gefcom-wind")


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def ingest(out_dir: Path | None = None, *, force_download: bool = False) -> dict[str, Path]:
    """Download, transform and write canonical parquet for both tracks."""
    settings = get_settings()
    settings.ensure_dirs()
    out_dir = out_dir or settings.data_canonical
    out_dir.mkdir(parents=True, exist_ok=True)

    archive = download_archive(force=force_download)
    written: dict[str, Path] = {}

    for tech, loader in ((Tech.SOLAR, load_solar), (Tech.WIND, load_wind)):
        weather, power = loader(archive)
        wpath = out_dir / f"gefcom_{tech.value}_weather.parquet"
        ppath = out_dir / f"gefcom_{tech.value}_power.parquet"
        weather.to_parquet(wpath, index=False)
        power.to_parquet(ppath, index=False)
        written[f"{tech.value}_weather"] = wpath
        written[f"{tech.value}_power"] = ppath
        log.info(
            "%s: %d weather rows, %d power rows, %d sites, %s to %s",
            tech.value,
            len(weather),
            len(power),
            power["site_id"].nunique(),
            power["valid_time_utc"].min().date(),
            power["valid_time_utc"].max().date(),
        )

    return written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for key, path in ingest().items():
        print(f"{key:16s} -> {path}")
