"""FastAPI service. The contract Phase 2 modules build against.

`POST /forecast` accepts either a registered `site_id` or a bare latitude/longitude plus
capacity. The second form is the point of the whole design: a site with no generation
history, absent from every training set, still gets a full 72-hour forecast with
uncertainty bands, because the model regresses a dimensionless quantity against weather
and site geometry rather than memorising individual plants.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

# The dashboard is served from its own origin - Vite on 5173 in development - so every call
# it makes to this API is cross-origin and the browser sends a preflight first. Without this
# middleware that preflight is answered with 405 and no allow-origin header, and the browser
# blocks every request before it reaches a route. Nothing shows up in the API log, which
# makes it look like a frontend bug when it is entirely a server one.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type"],
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


@lru_cache(maxsize=1)
def _trained_site_ids() -> frozenset[str]:
    """Sites that actually appear in a trained model's corpus.

    Read from the artifacts rather than inferred from the id. The previous version tested
    `site_id.startswith("GEFCOM-")`, which was true when GEFCom2014 was the training set and
    became false the moment the corpus moved to AEMO - after which all 151 trained plants
    reported themselves as never-seen. The flag is what the UI uses to mark a forecast as a
    genuine cold start, so getting it backwards undersells the one claim the platform most
    wants to make.
    """
    from reip.config import get_settings

    ids: set[str] = set()
    for tech in Tech:
        path = get_settings().artifacts_dir / f"{tech.value}_metadata.json"
        if path.exists():
            ids.update(json.loads(path.read_text(encoding="utf-8")).get("sites", []))
    return frozenset(ids)


@app.get("/sites")
def sites() -> list[dict[str, Any]]:
    """Every registered site, as a flat list.

    A bare array rather than an envelope: the count is `length`, and wrapping it only forces
    every consumer to unwrap it.
    """
    trained = _trained_site_ids()
    return [
        {
            "site_id": s.site_id,
            "name": s.name,
            "tech": s.tech.value,
            "capacity_mw": s.capacity_mw,
            "latitude": s.latitude,
            "longitude": s.longitude,
            # Empty string, not null: the field is a display label and a UI should not have
            # to special-case a site that dispatches into no market region.
            "region": s.market_region or "",
            "in_training_data": s.site_id in trained,
            "location_is_estimated": s.location_is_estimated,
        }
        for s in registry().all()
    ]


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
