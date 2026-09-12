"""Shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from reip.config import get_settings
from reip.schemas import SiteMeta, Tech
from reip.sites.registry import SiteRegistry


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def registry() -> SiteRegistry:
    return SiteRegistry.load()


def _first_site_with_data(registry: SiteRegistry, tech: Tech) -> SiteMeta:
    """A site that has both weather and power in the active corpus."""
    weather = _canonical("weather", tech.value)
    if weather is None:
        pytest.skip(f"no canonical {tech.value} weather; run the ingest first")
    available = set(weather["site_id"].unique())
    for site in registry.by_tech(tech):
        if site.site_id in available:
            return site
    pytest.skip(f"no {tech.value} site present in both registry and corpus")


@pytest.fixture(scope="session")
def solar_site(registry: SiteRegistry) -> SiteMeta:
    return _first_site_with_data(registry, Tech.SOLAR)


@pytest.fixture(scope="session")
def wind_site(registry: SiteRegistry) -> SiteMeta:
    return _first_site_with_data(registry, Tech.WIND)


@pytest.fixture(scope="session")
def gujarat_solar(registry: SiteRegistry) -> SiteMeta:
    """A real site with true coordinates that appears in no training data."""
    return registry.get("GJ-SOLAR-CHARANKA")


def _canonical(kind: str, tech: str) -> pd.DataFrame | None:
    """Load whichever corpus the pipeline is actually using.

    Tests must exercise the corpus the artifacts were trained on. Pinning them to GEFCom
    while the models train on AEMO would leave the skew test passing against data nothing
    in production touches - which is precisely the failure T1 exists to catch.
    """
    canonical = get_settings().data_canonical
    for corpus in ("aemo", "gefcom"):
        path = canonical / f"{corpus}_{tech}_{kind}.parquet"
        if path.exists():
            return pd.read_parquet(path)
    return None


@pytest.fixture(scope="session")
def solar_weather() -> pd.DataFrame:
    frame = _canonical("weather", "solar")
    if frame is None:
        pytest.skip("canonical solar weather absent; run an ingest module first")
    return frame


@pytest.fixture(scope="session")
def solar_power() -> pd.DataFrame:
    frame = _canonical("power", "solar")
    if frame is None:
        pytest.skip("canonical solar power absent; run an ingest module first")
    return frame


@pytest.fixture(scope="session")
def wind_weather() -> pd.DataFrame:
    frame = _canonical("weather", "wind")
    if frame is None:
        pytest.skip("canonical wind weather absent; run an ingest module first")
    return frame


@pytest.fixture(scope="session")
def benchmark() -> dict:
    path = get_settings().reports_dir / "benchmark.json"
    if not path.exists():
        pytest.skip("benchmark.json absent; run `python -m reip.eval.report`")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def artifacts_present() -> bool:
    return (get_settings().artifacts_dir / "solar_metadata.json").exists()


@pytest.fixture
def fixture_weather_payload() -> dict:
    path = Path("src/reip/ingest/fixtures/openmeteo_sample.json")
    if not path.exists():
        pytest.skip("Open-Meteo fixture absent")
    return json.loads(path.read_text(encoding="utf-8"))
