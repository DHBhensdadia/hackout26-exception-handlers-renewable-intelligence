"""The storage seam.

Phase 1 keeps canonical data as parquet on disk, which is the right choice for a batch
training pipeline: no service to run, no schema migrations, and the whole corpus loads in
under a second. Phase 2 turns ingestion continuous — scheduled weather pulls, live plant
telemetry, per-site incremental appends — and that is the point at which PostgreSQL earns
its complexity.

This protocol is where that swap happens. Everything downstream depends on the interface
rather than on `pd.read_parquet`, so `PostgresWeatherRepository` can be dropped in beside
`ParquetWeatherRepository` without the trainer, the feature builder or the API changing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd

from reip.config import get_settings
from reip.schemas import Tech, validate_power, validate_weather


class WeatherRepository(Protocol):
    """Read access to canonical weather and power frames."""

    def weather(self, tech: Tech, site_id: str | None = None) -> pd.DataFrame: ...
    def power(self, tech: Tech, site_id: str | None = None) -> pd.DataFrame: ...


class ParquetWeatherRepository:
    """Phase 1 implementation: canonical parquet files under `data/canonical`."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_settings().data_canonical

    def _read(self, name: str, site_id: str | None) -> pd.DataFrame:
        path = self._root / name
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found; run `python -m reip.ingest.gefcom` to build it"
            )
        frame = pd.read_parquet(path)
        return frame[frame["site_id"] == site_id] if site_id else frame

    def weather(self, tech: Tech, site_id: str | None = None) -> pd.DataFrame:
        return validate_weather(
            self._read(f"gefcom_{tech.value}_weather.parquet", site_id), name=f"{tech.value}-weather"
        )

    def power(self, tech: Tech, site_id: str | None = None) -> pd.DataFrame:
        return validate_power(
            self._read(f"gefcom_{tech.value}_power.parquet", site_id), name=f"{tech.value}-power"
        )


def default_repository() -> WeatherRepository:
    """The repository the pipeline uses. Phase 2 changes this one function."""
    return ParquetWeatherRepository()
