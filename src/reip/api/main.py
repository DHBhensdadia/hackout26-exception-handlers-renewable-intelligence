"""FastAPI service. The contract Phase 2 modules build against.

`POST /forecast` accepts either a registered `site_id` or a bare latitude/longitude plus
capacity. The second form is the point of the whole design: a site with no generation
history, absent from every training set, still gets a full 72-hour forecast with
uncertainty bands, because the model regresses a dimensionless quantity against weather
and site geometry rather than memorising individual plants.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from reip.config import MODEL_VERSION, get_settings
from reip.ingest.openmeteo import WeatherUnavailable, fetch_forecast
from reip.models.predict import ArtifactMissing, load_model, predict_site
from reip.schemas import ForecastRequest, SiteForecast, SiteMeta, Tech
from reip.sites.registry import SiteNotFound, SiteRegistry

log = logging.getLogger(__name__)

app = FastAPI(
    title="Renewable Energy Intelligence Platform - Forecasting API",
    version=MODEL_VERSION,
    description="24-72 hour solar and wind power forecasts with p10/p50/p90 uncertainty bands.",
)

_registry: SiteRegistry | None = None


def registry() -> SiteRegistry:
    global _registry  # noqa: PLW0603 - process-wide singleton, loaded once
    if _registry is None:
        _registry = SiteRegistry.load()
    return _registry


class HealthResponse(BaseModel):
    status: str
    model_version: str
    models_loaded: dict[str, bool]
    sites_registered: int
    weather_source: str


def resolve_site(request: ForecastRequest) -> SiteMeta:
    """Turn a request into site metadata, whether registered or ad hoc."""
    if request.site_id:
        try:
            site = registry().get(request.site_id)
        except SiteNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        overrides = {
            k: v
            for k, v in (
                ("tilt_deg", request.tilt_deg),
                ("azimuth_deg", request.azimuth_deg),
                ("hub_height_m", request.hub_height_m),
                ("capacity_mw", request.capacity_mw),
            )
            if v is not None
        }
        return site.model_copy(update=overrides).defaulted if overrides else site

    # Ad-hoc site: never seen in training, constructed entirely from the request.
    assert request.tech is not None and request.capacity_mw is not None  # noqa: S101
    return SiteMeta(
        site_id=f"adhoc-{request.latitude:.4f},{request.longitude:.4f}",
        name="Ad-hoc site",
        tech=request.tech,
        capacity_mw=request.capacity_mw,
        latitude=float(request.latitude),  # type: ignore[arg-type]
        longitude=float(request.longitude),  # type: ignore[arg-type]
        tilt_deg=request.tilt_deg,
        azimuth_deg=request.azimuth_deg,
        hub_height_m=request.hub_height_m,
    ).defaulted


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    loaded: dict[str, bool] = {}
    for tech in Tech:
        try:
            load_model(tech)
            loaded[tech.value] = True
        except (ArtifactMissing, FileNotFoundError):
            loaded[tech.value] = False

    return HealthResponse(
        status="ok" if any(loaded.values()) else "degraded",
        model_version=MODEL_VERSION,
        models_loaded=loaded,
        sites_registered=len(registry()),
        weather_source=f"openmeteo:{get_settings().openmeteo_model}",
    )


@app.get("/sites")
def sites() -> dict[str, Any]:
    """Registered sites. The GJ-* entries are Gujarat demo sites absent from all training data."""
    return {
        "count": len(registry()),
        "sites": [
            {
                "site_id": s.site_id,
                "name": s.name,
                "tech": s.tech.value,
                "capacity_mw": s.capacity_mw,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "in_training_data": s.site_id.startswith("GEFCOM-"),
                "location_is_estimated": s.location_is_estimated,
            }
            for s in registry().all()
        ],
    }


@app.post("/forecast", response_model=SiteForecast)
def forecast(request: ForecastRequest) -> SiteForecast:
    """24-72 hour power forecast with uncertainty bands."""
    site = resolve_site(request)

    try:
        load_model(site.tech)
    except (ArtifactMissing, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"no trained {site.tech.value} model available; run reip.models.train",
        ) from exc

    issue_time = pd.Timestamp(datetime.now(UTC)).floor("h")
    try:
        weather = fetch_forecast(site, horizon_h=request.horizon_h, issue_time=issue_time)
    except WeatherUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"weather unavailable: {exc}") from exc

    try:
        return predict_site(weather, site, issue_time=issue_time)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
