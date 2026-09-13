"""Canonical data contracts for the forecasting platform.

Everything in this file is a contract. Ingest adapters produce these shapes,
the feature builder consumes them, and the API returns them. Downstream Phase 2+
modules (surplus/shortage, storage dispatch, investment optimisation) are built
against `SiteForecast` and must not depend on anything upstream of it.

Two representations exist deliberately:
  * pydantic models  -> API boundary, single records, validation with good errors
  * column constants -> dataframe boundary, bulk pipeline, validated by `validate_frame`

Keeping both in one file is what stops them drifting apart.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------------------


class Tech(StrEnum):
    """Generation technology. Drives which model, physics module and features apply."""

    SOLAR = "solar"
    WIND = "wind"


class Mount(StrEnum):
    """PV module mounting geometry."""

    FIXED = "fixed"
    SINGLE_AXIS = "single_axis"


class Quantile(StrEnum):
    """The three quantiles we forecast. Spec section 26 requires uncertainty, not points."""

    P10 = "p10"
    P50 = "p50"
    P90 = "p90"

    @property
    def alpha(self) -> float:
        return {"p10": 0.10, "p50": 0.50, "p90": 0.90}[self.value]


QUANTILES: Final[tuple[Quantile, ...]] = (Quantile.P10, Quantile.P50, Quantile.P90)

# Forecast horizon bounds. Spec section 3A: 24-72 hours.
MIN_HORIZON_H: Final[int] = 1
MAX_HORIZON_H: Final[int] = 72

# Lead-time buckets used for every evaluation table. A single headline metric hides
# the thing that actually matters, which is how fast skill decays with lead time.
LEAD_BUCKETS: Final[tuple[tuple[str, int, int], ...]] = (
    ("1-24h", 1, 24),
    ("25-48h", 25, 48),
    ("49-72h", 49, 72),
)


def lead_bucket(horizon_h: int) -> str:
    """Map an hour-ahead horizon to its evaluation bucket label."""
    for label, lo, hi in LEAD_BUCKETS:
        if lo <= horizon_h <= hi:
            return label
    return "out-of-range"


# --------------------------------------------------------------------------------------
# Physical bounds. Used as assertions at ingest, not as documentation.
# --------------------------------------------------------------------------------------

MAX_GHI_WM2: Final[float] = 1400.0  # above the solar constant at sea level -> data error
MAX_WIND_SPEED_MS: Final[float] = 90.0
AIR_DENSITY_BOUNDS: Final[tuple[float, float]] = (0.9, 1.4)  # kg/m3, test T3
CLEARSKY_INDEX_MAX: Final[float] = 1.3  # cloud enhancement is real, but bounded
NIGHT_GHI_THRESHOLD_WM2: Final[float] = 5.0  # below this we force power to zero

# --------------------------------------------------------------------------------------
# Canonical weather frame
# --------------------------------------------------------------------------------------

WEATHER_KEY: Final[list[str]] = ["site_id", "issue_time_utc", "valid_time_utc"]

WEATHER_COLUMNS: Final[dict[str, str]] = {
    # identity / time
    "site_id": "string",
    "issue_time_utc": "datetime64[ns, UTC]",
    "valid_time_utc": "datetime64[ns, UTC]",
    "horizon_h": "int16",
    # irradiance
    "ghi_wm2": "float32",
    "dni_wm2": "float32",
    "dhi_wm2": "float32",
    # cloud
    "cloud_total": "float32",
    "cloud_low": "float32",
    "cloud_mid": "float32",
    "cloud_high": "float32",
    # thermodynamic
    "temp_2m_c": "float32",
    "rh_pct": "float32",
    "pressure_hpa": "float32",
    "precip_mm": "float32",
    # wind
    "wind_speed_10m": "float32",
    "wind_speed_100m": "float32",
    "wind_dir_10m_deg": "float32",
    "wind_dir_100m_deg": "float32",
    # provenance: "gefcom" | "openmeteo:icon_seamless" | "fixture"
    "source": "string",
}

# The canonical weather frame is the UNION of what any provider can supply, so only
# identity and time are universally required. Real sources are each missing something:
# the GEFCom solar track has no 100 m wind, the GEFCom wind track has no temperature or
# pressure at all, Open-Meteo has everything. Rather than invent values to satisfy a
# rigid schema, absence is recorded as NaN and each consumer declares its own needs via
# `require_columns` below.
#
# Missing must never become zero. For irradiance and cloud cover zero is a real physical
# value, so coercing absence to zero would teach the model that a provider which omits a
# field is reporting permanent darkness.
WEATHER_REQUIRED: Final[frozenset[str]] = frozenset(
    {"site_id", "issue_time_utc", "valid_time_utc", "horizon_h", "source"}
)
WEATHER_OPTIONAL: Final[frozenset[str]] = frozenset(WEATHER_COLUMNS) - WEATHER_REQUIRED

# What each technology's feature builder actually needs present and non-null.
SOLAR_REQUIRED_WEATHER: Final[tuple[str, ...]] = ("ghi_wm2", "temp_2m_c", "wind_speed_10m")
WIND_REQUIRED_WEATHER: Final[tuple[str, ...]] = ("wind_speed_10m", "wind_speed_100m")


def require_columns(df: pd.DataFrame, needed: tuple[str, ...], *, context: str) -> None:
    """Assert a frame carries the columns a consumer depends on, with real values.

    Checked at the point of use rather than at ingest, because a frame that is perfectly
    valid for wind (no irradiance) is useless for solar, and the schema alone cannot
    know which one it is about to be used for.
    """
    absent = [c for c in needed if c not in df.columns]
    if absent:
        raise SchemaError(f"{context}: required columns absent {absent}")
    empty = [c for c in needed if df[c].isna().all()]
    if empty:
        raise SchemaError(f"{context}: required columns present but entirely null {empty}")


# --------------------------------------------------------------------------------------
# Canonical power frame
# --------------------------------------------------------------------------------------

POWER_KEY: Final[list[str]] = ["site_id", "valid_time_utc"]

POWER_COLUMNS: Final[dict[str, str]] = {
    "site_id": "string",
    "valid_time_utc": "datetime64[ns, UTC]",
    "tech": "string",
    "power_mw": "float32",
    "capacity_mw": "float32",
    "is_valid": "bool",
}


# --------------------------------------------------------------------------------------
# Frame validation
# --------------------------------------------------------------------------------------


class SchemaError(ValueError):
    """Raised when a dataframe violates a canonical contract."""


def _missing_value(dtype: str) -> object:
    """The correct null for a pandas dtype.

    Absent optional columns must be genuinely missing, never zero: for irradiance and
    cloud cover zero is a real physical value, so coercing absence to zero would teach
    the model that a source which omits a field always reports darkness.
    """
    if dtype.startswith(("float", "datetime")):
        return float("nan") if dtype.startswith("float") else pd.NaT
    if dtype.startswith("int"):
        raise SchemaError(f"integer column cannot be optional (dtype {dtype})")
    if dtype == "bool":
        return False
    return pd.NA


def validate_frame(
    df: pd.DataFrame,
    columns: dict[str, str],
    key: list[str],
    *,
    optional: frozenset[str] = frozenset(),
    name: str = "frame",
) -> pd.DataFrame:
    """Validate and coerce a dataframe to a canonical contract.

    Enforces: no missing required columns, correct dtypes, no duplicate keys, and
    UTC-aware timestamps. Returns a new frame with columns in contract order so that
    anything comparing two canonical frames compares like with like.

    Raises SchemaError rather than warning. A silently-wrong frame here becomes a
    silently-wrong model later, which is far more expensive to discover.
    """
    missing = [c for c in columns if c not in df.columns and c not in optional]
    if missing:
        raise SchemaError(f"{name}: missing required columns {missing}")

    out = df.copy()
    for col, dtype in columns.items():
        if col not in out.columns:
            # Create at the target dtype directly. Filling with pd.NA in an object
            # column then casting fails for float32, and the resulting error would
            # mask whatever real validation ran after it.
            out[col] = pd.Series(_missing_value(dtype), index=out.index, dtype=dtype)
        if dtype.startswith("datetime64"):
            ts = pd.to_datetime(out[col], utc=True, errors="coerce")
            if ts.isna().any() and not out[col].isna().all():
                raise SchemaError(f"{name}.{col}: unparseable timestamps present")
            out[col] = ts
        else:
            try:
                out[col] = out[col].astype(dtype)
            except (TypeError, ValueError) as exc:
                raise SchemaError(f"{name}.{col}: cannot cast to {dtype} ({exc})") from exc

    dupes = out.duplicated(subset=key, keep=False)
    if dupes.any():
        raise SchemaError(f"{name}: {int(dupes.sum())} rows duplicate the key {key}")

    return out[list(columns)]


def validate_weather(df: pd.DataFrame, *, name: str = "weather") -> pd.DataFrame:
    """Validate a canonical weather frame and assert physical plausibility (test T5)."""
    out = validate_frame(df, WEATHER_COLUMNS, WEATHER_KEY, optional=WEATHER_OPTIONAL, name=name)

    if (out["horizon_h"] < 0).any():
        raise SchemaError(f"{name}: negative horizon_h - issue_time is after valid_time")

    # Recompute rather than trust: horizon_h is derived, and a source that gets it
    # wrong would shift every lead-time feature by a constant.
    expected = ((out["valid_time_utc"] - out["issue_time_utc"]).dt.total_seconds() / 3600.0).round()
    mismatch = (expected != out["horizon_h"].astype("float64")).sum()
    if mismatch:
        raise SchemaError(f"{name}: horizon_h inconsistent with timestamps on {int(mismatch)} rows")

    for col in ("ghi_wm2", "dni_wm2", "dhi_wm2"):
        vals = out[col].dropna()
        if len(vals) and (vals < -1.0).any():
            raise SchemaError(f"{name}.{col}: negative irradiance (de-accumulation bug?)")
        if len(vals) and (vals > MAX_GHI_WM2).any():
            raise SchemaError(
                f"{name}.{col}: exceeds {MAX_GHI_WM2} W/m2 (unit or accumulation bug?)"
            )

    for col in ("wind_speed_10m", "wind_speed_100m"):
        vals = out[col].dropna()
        if len(vals) and ((vals < 0) | (vals > MAX_WIND_SPEED_MS)).any():
            raise SchemaError(f"{name}.{col}: outside [0, {MAX_WIND_SPEED_MS}] m/s")

    return out


def validate_power(df: pd.DataFrame, *, name: str = "power") -> pd.DataFrame:
    """Validate a canonical power frame."""
    out = validate_frame(df, POWER_COLUMNS, POWER_KEY, name=name)

    bad_tech = set(out["tech"].dropna().unique()) - {t.value for t in Tech}
    if bad_tech:
        raise SchemaError(f"{name}.tech: unknown values {sorted(bad_tech)}")

    if (out["capacity_mw"] <= 0).any():
        raise SchemaError(f"{name}.capacity_mw: must be positive")

    valid = out[out["is_valid"]]
    if len(valid) and (valid["power_mw"] < -0.01 * valid["capacity_mw"]).any():
        raise SchemaError(f"{name}.power_mw: materially negative on rows marked valid")

    return out


# --------------------------------------------------------------------------------------
# Site metadata
# --------------------------------------------------------------------------------------


class SiteMeta(BaseModel):
    """Physical description of a generation site.

    These fields are the only site-specific inputs the model receives. Because the
    regression target is dimensionless (clear-sky index / capacity factor), a site
    that has never been seen in training can still be forecast from metadata alone -
    that is the multi-site generalisation claim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str
    name: str = ""
    tech: Tech
    capacity_mw: float = Field(gt=0)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = 0.0
    timezone: str = "UTC"

    # Solar-only geometry. Defaults are the standard fixed-tilt heuristic
    # (tilt ~= |latitude|, facing the equator) and are applied in `defaulted`.
    tilt_deg: float | None = Field(default=None, ge=0, le=90)
    azimuth_deg: float | None = Field(default=None, ge=0, le=360)
    dc_ac_ratio: float = Field(default=1.2, gt=0)

    # How the modules are mounted. This is not a detail: a horizontal single-axis tracker
    # follows the sun east to west, so it produces a wide flat-topped day with a steep
    # morning ramp, where a fixed array produces a narrow bell. Modelling a tracking plant
    # as fixed underestimates its morning and evening output several-fold, which makes the
    # clear-sky index - the solar regression target - explode at exactly those hours.
    # Most utility-scale plants built in the last decade track.
    mount: Mount = Mount.FIXED

    # Wind-only turbine geometry.
    hub_height_m: float | None = Field(default=None, gt=0)
    rotor_diameter_m: float | None = Field(default=None, gt=0)
    rated_ws_ms: float = Field(default=12.0, gt=0)
    cut_in_ws_ms: float = Field(default=3.0, ge=0)
    cut_out_ws_ms: float = Field(default=25.0, gt=0)

    # Set when latitude/longitude were recovered by fitting rather than known
    # (GEFCom zones are anonymised). Surfaced so the report can be honest about it.
    location_is_estimated: bool = False

    # Market region the site dispatches into - NSW1, QLD1, SA1, TAS1, VIC1 for the NEM.
    #
    # The forecasting model has no use for this: it predicts one plant from weather and
    # geometry, and a market boundary is not a physical input. Everything downstream does,
    # because demand, price and the balance equation are all defined per region, and a
    # plant can only be netted against the load it can actually reach.
    #
    # Optional because GEFCom zones and any ad-hoc lat/lon the API is handed have no
    # region at all. Consumers that need one must say so rather than assume.
    market_region: str | None = None

    @field_validator("site_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("site_id must not be blank")
        return v

    @model_validator(mode="after")
    def _check_turbine(self) -> SiteMeta:
        if self.cut_out_ws_ms <= self.cut_in_ws_ms:
            raise ValueError("cut_out_ws_ms must exceed cut_in_ws_ms")
        if not (self.cut_in_ws_ms < self.rated_ws_ms < self.cut_out_ws_ms):
            raise ValueError("rated_ws_ms must lie between cut-in and cut-out")
        return self

    @property
    def defaulted(self) -> SiteMeta:
        """Fill technology-appropriate defaults for unset geometry.

        Called once at registry load so downstream code never handles `None`.
        """
        patch: dict[str, float] = {}
        if self.tech is Tech.SOLAR:
            if self.tilt_deg is None:
                patch["tilt_deg"] = min(abs(self.latitude), 40.0)
            if self.azimuth_deg is None:
                patch["azimuth_deg"] = 180.0 if self.latitude >= 0 else 0.0
        else:
            if self.hub_height_m is None:
                patch["hub_height_m"] = 100.0
            if self.rotor_diameter_m is None:
                patch["rotor_diameter_m"] = 90.0
        return self.model_copy(update=patch) if patch else self


# --------------------------------------------------------------------------------------
# Forecast output - the contract Phase 2+ modules consume
# --------------------------------------------------------------------------------------


class ForecastPoint(BaseModel):
    """One hour of the forecast.

    `clearsky_mw` and `physics_mw` are returned alongside the prediction on purpose:
    they let a consumer render "forecast vs theoretical maximum" without a second call,
    and they make every prediction auditable against the physics it was corrected from.
    """

    model_config = ConfigDict(extra="forbid")

    valid_time_utc: datetime
    horizon_h: int = Field(ge=MIN_HORIZON_H, le=MAX_HORIZON_H)
    p10_mw: float = Field(ge=0)
    p50_mw: float = Field(ge=0)
    p90_mw: float = Field(ge=0)
    clearsky_mw: float = Field(ge=0)
    physics_mw: float = Field(ge=0)

    @model_validator(mode="after")
    def _monotone_quantiles(self) -> ForecastPoint:
        # Quantile crossing is a real failure mode of independently-fitted quantile
        # models. predict.py sorts to prevent it; this is the backstop that proves it did.
        if not (self.p10_mw <= self.p50_mw <= self.p90_mw):
            raise ValueError(
                f"quantile crossing at horizon {self.horizon_h}: "
                f"p10={self.p10_mw} p50={self.p50_mw} p90={self.p90_mw}"
            )
        return self


class SiteForecast(BaseModel):
    """A full 24-72h forecast for one site. The platform's central object."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    tech: Tech
    issue_time_utc: datetime
    capacity_mw: float = Field(gt=0)
    model_version: str
    weather_source: str
    location_is_estimated: bool = False
    points: list[ForecastPoint]

    @model_validator(mode="after")
    def _contiguous_horizons(self) -> SiteForecast:
        if not self.points:
            raise ValueError("forecast contains no points")
        horizons = [p.horizon_h for p in self.points]
        if horizons != sorted(horizons):
            raise ValueError("points must be ordered by horizon_h")
        if len(set(horizons)) != len(horizons):
            raise ValueError("duplicate horizon_h in points")
        return self

    def to_frame(self) -> pd.DataFrame:
        """Flatten to a dataframe. This is the handoff shape for Phase 2 modules."""
        return pd.DataFrame(
            [
                {
                    "site_id": self.site_id,
                    "tech": self.tech.value,
                    "issue_time_utc": self.issue_time_utc,
                    "capacity_mw": self.capacity_mw,
                    **p.model_dump(),
                }
                for p in self.points
            ]
        )


class ForecastRequest(BaseModel):
    """POST /forecast body.

    Either `site_id` (a registered site) or latitude+longitude+tech+capacity_mw
    (an ad-hoc, never-before-seen site) is required. The second form is the
    cold-start path.
    """

    model_config = ConfigDict(extra="forbid")

    site_id: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    tech: Tech | None = None
    capacity_mw: float | None = Field(default=None, gt=0)
    horizon_h: int = Field(default=MAX_HORIZON_H, ge=MIN_HORIZON_H, le=MAX_HORIZON_H)

    tilt_deg: float | None = Field(default=None, ge=0, le=90)
    azimuth_deg: float | None = Field(default=None, ge=0, le=360)
    hub_height_m: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _identifiable(self) -> ForecastRequest:
        if self.site_id:
            return self
        missing = [
            f for f in ("latitude", "longitude", "tech", "capacity_mw") if getattr(self, f) is None
        ]
        if missing:
            raise ValueError(
                f"provide site_id, or all of latitude/longitude/tech/capacity_mw "
                f"(missing: {missing})"
            )
        return self
