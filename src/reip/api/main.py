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
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from reip.config import MODEL_VERSION, get_settings
from reip.ingest.openmeteo import WeatherUnavailable, fetch_forecast
from reip.models.predict import ArtifactMissing, load_model, predict_site
from reip.schemas import (
    MAX_HORIZON_H,
    MIN_HORIZON_H,
    ForecastRequest,
    SiteForecast,
    SiteMeta,
    Tech,
)
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


@app.get("/regions")
def regions() -> list[dict[str, Any]]:
    """Market regions, with the demand model's measured accuracy for each.

    Carries per-region `nmae_pct` and `coverage_pct` rather than only capacity, because a
    dashboard that shows a regional forecast should be able to say how good it is there -
    and it is not uniformly good. VIC1 covers 66.9% against a nominal 80%, so it ships a
    `caveat` the UI can surface instead of presenting every region at parity.
    """
    available = {p.stem.removeprefix("balance_") for p in _balance_files()}
    demand_meta = _demand_metadata()
    by_region = demand_meta.get("test", {}).get("by_region", {})

    out = []
    for code in registry().regions():
        stats = by_region.get(code, {})
        coverage = stats.get("coverage_calibrated")
        entry: dict[str, Any] = {
            # Both spellings. `region_id` is what the dashboard types expect; `region` is
            # what every other endpoint in this API uses as the path and body key, and
            # dropping either would break one of them.
            "region_id": code,
            "region": code,
            "name": _REGION_NAMES.get(code, code),
            "nmae_pct": stats.get("model_nmae_pct"),
            "coverage_pct": None if coverage is None else round(100 * coverage, 1),
            "headroom_mw": _headroom(code),
            "balance_available": code in available,
            "technologies": {},
        }
        if coverage is not None and not 0.72 <= coverage <= 0.90:
            entry["caveat"] = (
                f"Demand interval covers {100 * coverage:.0f}% against a nominal 80% here - "
                "seasonal bias no single correction reaches."
            )

        total = 0.0
        for tech in Tech:
            group = registry().by_region(code, tech)
            if not group:
                continue
            capacity = round(sum(s.capacity_mw for s in group), 1)
            total += capacity
            entry["technologies"][tech.value] = {"sites": len(group), "capacity_mw": capacity}
        entry["total_capacity_mw"] = round(total, 1)
        out.append(entry)
    return out


# Display names. The NEM codes are opaque outside Australia, and a region picker showing
# "SA1" tells a reader less than "South Australia".
_REGION_NAMES: dict[str, str] = {
    "NSW1": "New South Wales",
    "QLD1": "Queensland",
    "SA1": "South Australia",
    "TAS1": "Tasmania",
    "VIC1": "Victoria",
}


@lru_cache(maxsize=1)
def _demand_metadata() -> dict:
    path = get_settings().artifacts_dir / "demand_metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _headroom(region: str) -> float | None:
    """Measured dispatchable headroom, from the precomputed balance window."""
    try:
        return _load_balance(region).get("dispatchable_headroom_mw")
    except FileNotFoundError:
        return None


def _balance_files() -> list[Path]:
    from reip.balance.precompute import artifact_path

    directory = artifact_path("X").parent
    return sorted(directory.glob("balance_*.json")) if directory.exists() else []


@lru_cache(maxsize=8)
def _load_balance(region: str) -> dict:
    from reip.balance.precompute import artifact_path

    path = artifact_path(region)
    if not path.exists():
        raise FileNotFoundError(region)
    return json.loads(path.read_text(encoding="utf-8"))


class BalanceRequest(BaseModel):
    """POST /balance body."""

    model_config = ConfigDict(extra="forbid")

    region: str
    horizon_h: int = Field(default=MAX_HORIZON_H, ge=MIN_HORIZON_H, le=MAX_HORIZON_H)


def _balance_payload(region: str) -> dict:
    """Load a precomputed balance window, or 404 with what is available."""
    code = region.strip().upper()
    try:
        return dict(_load_balance(code))
    except FileNotFoundError:
        known = sorted(p.stem.removeprefix("balance_") for p in _balance_files())
        raise HTTPException(
            status_code=404,
            detail=f"no balance window for region {code!r}; available: {known or 'none'}",
        ) from None


@app.post("/balance")
def regional_balance(request: BalanceRequest) -> dict[str, Any]:
    """Regional generation against regional demand, as calibrated probabilities.

    Served from a precomputed window rather than computed per request. One window means
    forecasting every plant in the region, drawing a coherent ensemble across all of them
    and forecasting demand - minutes of work, and not something to do inside an HTTP call.

    The window is a replay of real held-out history; `data_mode` says so in the payload.
    The demand model needs load at the issue time, and the market corpus ends before today,
    so there is no honest way to serve tonight until that ingest runs to the present.
    """
    payload = _balance_payload(request.region)

    # Trim to the requested horizon rather than ignoring it: the dashboard's horizon control
    # should do something, and the points are already ordered by lead time.
    payload["points"] = payload["points"][: request.horizon_h]
    payload["actual"] = payload.get("actual", [])[: request.horizon_h]
    payload["horizon_h"] = request.horizon_h
    return payload


@app.get("/seasonal/{region}")
def seasonal(region: str) -> dict[str, Any]:
    """Recurring patterns mined from three years of measured history.

    Not a forecast and not derived from one. A recurring pattern is a property of the record,
    so this is metered demand, the intermittent fleet's available output, spot price and
    actual curtailment - which is why `data_mode` is `measured` rather than `replay`.
    """
    from reip.seasonal.patterns import artifact_path as seasonal_path

    path = seasonal_path(region.strip().upper())
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no seasonal analysis for {region!r}; run `python -m reip.seasonal.patterns`",
        )
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/demand/{region}")
def demand(region: str) -> dict[str, Any]:
    """Regional demand forecast, p10/p50/p90, over the same window as `/balance`.

    Taken from the balance ensemble rather than re-predicted, so the two cannot disagree
    about what demand was expected to do.
    """
    payload = _balance_payload(region)
    return {
        "region": payload["region"],
        "issue_time_utc": payload["issue_time_utc"],
        "model_version": payload["model_version"],
        "data_mode": payload["data_mode"],
        **payload["demand"],
        "actual_mw": [a["demand_mw"] for a in payload.get("actual", [])],
    }


class DemandRequest(BaseModel):
    """POST /demand body, in the shape the dashboard types expect."""

    model_config = ConfigDict(extra="forbid")

    region_id: str
    horizon_h: int = Field(default=MAX_HORIZON_H, ge=MIN_HORIZON_H, le=MAX_HORIZON_H)


@app.post("/demand")
def demand_band(request: DemandRequest) -> dict[str, Any]:
    """Regional demand band as a list of points, with the model's measured accuracy.

    Same numbers as `GET /demand/{region}`, shaped as `points[]` rather than parallel
    arrays because that is what the dashboard consumes. `nmae_pct` and `coverage_pct` ride
    along so a panel can state how good the model is in that specific region without a
    second request.
    """
    code = request.region_id.strip().upper()
    payload = _balance_payload(code)
    band = payload["demand"]
    stats = _demand_metadata().get("test", {}).get("by_region", {}).get(code, {})
    coverage = stats.get("coverage_calibrated")

    points = [
        {
            "valid_time_utc": t,
            "horizon_h": i + 1,
            "p10_mw": lo,
            "p50_mw": mid,
            "p90_mw": hi,
        }
        for i, (t, lo, mid, hi) in enumerate(
            zip(band["valid_time_utc"], band["p10_mw"], band["p50_mw"], band["p90_mw"], strict=True)
        )
    ][: request.horizon_h]

    return {
        "region_id": code,
        "data_mode": payload["data_mode"],
        "model_version": payload["model_version"],
        "nmae_pct": stats.get("model_nmae_pct"),
        "coverage_pct": None if coverage is None else round(100 * coverage, 1),
        "points": points,
        "source": "api",
    }


@app.get("/vss")
def value_of_stochastic_solution() -> list[dict[str, Any]]:
    """What planning against the scenario ensemble is worth, against planning on the median.

    The number the whole uncertainty chain exists to justify. Regions where it is zero are
    returned rather than filtered: a metric honest about where it does not apply is worth
    more than one that only reports its wins.
    """
    path = get_settings().reports_dir / "vss.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail="no VSS report; run `python -m reip.eval.vss`")
    return json.loads(path.read_text(encoding="utf-8"))


class StorageRequest(BaseModel):
    """POST /storage/dispatch body. Battery parameters are the caller's to choose."""

    model_config = ConfigDict(extra="forbid")

    region: str
    energy_mwh: float = Field(default=200.0, gt=0, le=100_000)
    power_mw: float = Field(default=100.0, gt=0, le=50_000)
    efficiency: float = Field(default=0.88, gt=0, le=1)
    initial_soc: float = Field(default=0.5, ge=0, le=1)


@app.post("/storage/dispatch")
def storage_dispatch(request: StorageRequest) -> dict[str, Any]:
    """Optimal battery schedule against the region's scenario ensemble.

    Solved live - the LP takes well under a second because dropping the redundant
    charge/discharge binary keeps it linear - so battery size and power are genuinely
    interactive rather than fixed at precompute time.

    Hour 1 is a firm commitment, identical across every scenario; later hours are recourse
    and will be re-optimised as forecasts update. The response separates the two.
    """
    import numpy as np

    from reip.balance.precompute import ensemble_path
    from reip.storage.asset import GridLimits, StorageAsset, grid_limits_from_market
    from reip.storage.dispatch import solve

    code = request.region.strip().upper()
    path = ensemble_path(code)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no scenario ensemble for {code!r}; run `python -m reip.balance.precompute`",
        )

    with np.load(path) as bundle:
        renewable = bundle["renewable_mw"]
        demand_mw = bundle["demand_mw"]
        price = bundle["price_aud_mwh"]
        headroom = float(bundle["headroom_mw"][0])

    try:
        asset = StorageAsset(
            energy_mwh=request.energy_mwh,
            power_mw=request.power_mw,
            efficiency=request.efficiency,
            initial_soc=max(0.05, min(request.initial_soc, 0.95)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    grid: GridLimits = grid_limits_from_market(code)
    # Fewer scenarios than the balance uses: the LP is linear in scenario count and solved
    # inside a request, and 50 keeps the tails wide enough to matter while staying instant.
    keep = min(50, renewable.shape[0])
    result = solve(
        renewable_mw=renewable[:keep],
        demand_mw=demand_mw[:keep],
        price_aud_mwh=price,
        asset=asset,
        grid=grid,
        dispatchable_mw=headroom,
    )

    schedule = result.schedule.round(2)
    return {
        "region": code,
        "n_scenarios": result.n_scenarios,
        "data_mode": "replay",
        "asset": {
            "energy_mwh": asset.energy_mwh,
            "power_mw": asset.power_mw,
            "duration_h": round(asset.duration_h, 2),
            "efficiency": asset.efficiency,
        },
        "grid": {
            "import_limit_mw": round(grid.import_limit_mw, 1),
            "export_limit_mw": round(grid.export_limit_mw, 1),
        },
        "dispatchable_headroom_mw": round(headroom, 1),
        "expected_cost_aud": round(result.expected_cost_aud, 2),
        # Hour 1 is the decision actually being committed to; everything after it is a plan.
        "committed": {
            "action": result.committed_action,
            "charge_mw": round(result.committed_charge_mw, 2),
            "discharge_mw": round(result.committed_discharge_mw, 2),
        },
        "schedule": schedule.to_dict("records"),
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
