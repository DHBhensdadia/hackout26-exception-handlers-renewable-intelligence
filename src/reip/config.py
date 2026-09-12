"""Runtime configuration. Every path and tunable lives here, nothing hardcoded downstream."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

MODEL_VERSION: Final[str] = "xgb-q-0.1.0"


class Settings(BaseSettings):
    """Environment-overridable settings. Prefix every env var with REIP_."""

    model_config = SettingsConfigDict(env_prefix="REIP_", env_file=".env", extra="ignore")

    # --- paths -------------------------------------------------------------------
    data_raw: Path = PROJECT_ROOT / "data" / "raw"
    data_canonical: Path = PROJECT_ROOT / "data" / "canonical"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"
    reports_dir: Path = PROJECT_ROOT / "reports"
    cache_dir: Path = PROJECT_ROOT / ".cache"
    sites_file: Path = PROJECT_ROOT / "src" / "reip" / "sites" / "sites.yaml"

    # --- weather -----------------------------------------------------------------
    # ICON seamless is the default: it publishes direct and diffuse radiation as native
    # model output rather than deriving them, which matters for the solar features.
    openmeteo_model: str = "icon_seamless"
    openmeteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    openmeteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    openmeteo_historical_forecast_url: str = (
        "https://historical-forecast-api.open-meteo.com/v1/forecast"
    )
    openmeteo_timeout_s: float = 20.0
    weather_cache_ttl_s: int = 3600  # one issue hour; keeps us inside the free tier

    # --- model -------------------------------------------------------------------
    # XGBoost is the spec's named backend (section 24). LightGBM remains available and is
    # benchmarked in reports/backend_comparison.md: the two are within 0.15pp of each other
    # on nMAE, and XGBoost's p10-p90 interval is the better calibrated of the pair.
    backend: Literal["lightgbm", "xgboost"] = "xgboost"

    # How the solar target is normalised.
    #
    # `clearsky_index` (power / clear-sky power) is the textbook choice and was clearly
    # better on GEFCom2014, whose power was already normalised and unclipped. On real
    # metered plants it breaks down: a heavily DC-oversized farm holds its export limit for
    # hours, so the ratio is governed by inverter clipping rather than by cloud. Measured
    # on the AEMO corpus, NWP cloudiness correlates -0.09 with the clear-sky index but
    # +0.32 with capacity factor.
    #
    # `capacity_factor` therefore leads for real plants. The clear-sky curve is not
    # discarded - it stays in the feature set as `clearsky_cf`, so the model still receives
    # the sun's deterministic trajectory; it simply no longer divides by it.
    solar_target: Literal["clearsky_index", "capacity_factor"] = "capacity_factor"
    random_seed: int = 42
    # Fraction of the timeline held out as a contiguous final block. Never shuffled:
    # a random split leaks future into past and manufactures a fake accuracy number.
    holdout_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    cv_folds: int = 3
    early_stopping_rounds: int = 100
    max_boost_rounds: int = 2000

    def ensure_dirs(self) -> None:
        for p in (
            self.data_raw,
            self.data_canonical,
            self.artifacts_dir,
            self.reports_dir,
            self.cache_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
