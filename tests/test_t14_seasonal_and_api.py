"""T14 - seasonal patterns must describe the record, and every endpoint must answer."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from reip.api.main import app
from reip.config import get_settings
from reip.seasonal import patterns


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def sa1() -> dict:
    path = patterns.artifact_path("SA1")
    if not path.exists():
        pytest.skip("seasonal artifact absent; run `python -m reip.seasonal.patterns`")
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- share arithmetic


def test_renewable_share_is_an_energy_ratio_not_a_mean_of_ratios():
    """The bug this replaced reported SA1 at a 1590% mean renewable share.

    Operational demand goes negative when rooftop PV exceeds all consumption - 257 hours a
    year in SA1 - so a per-hour renewable/demand ratio divides by something near zero, and
    averaging those ratios diverges. A ratio of sums does not.
    """
    demand = pd.Series([1000.0, 500.0, -100.0, 800.0])
    renewable = pd.Series([400.0, 400.0, 400.0, 400.0])

    naive = float((renewable / demand.clip(lower=1.0)).mean())
    correct = patterns._energy_share(renewable, demand)

    assert naive > 1.0, "the naive mean-of-ratios should blow up on this input"
    assert correct == pytest.approx(1600 / 2200)
    assert 0 < correct < 1


def test_share_is_none_when_demand_energy_is_not_positive():
    assert np.isnan(patterns._energy_share(pd.Series([10.0]), pd.Series([-5.0])))


def test_monthly_shares_are_physically_plausible(sa1):
    """A region cannot supply 1590% of its own demand over a month."""
    shares = [m["renewable_share"] for m in sa1["by_month"] if m["renewable_share"] is not None]
    assert shares, "no monthly shares computed"
    assert all(0 <= s <= 1.6 for s in shares), f"implausible monthly shares: {shares}"


# ----------------------------------------------------------------- droughts


def test_droughts_are_measured_in_days_not_hours(sa1):
    """Scored hourly, a solar region is in drought every night by definition.

    QLD1 came out at 335 events a year on the hourly definition - one per night, which is the
    diurnal cycle, not a planning event.
    """
    droughts = sa1["droughts"]
    assert "days_per_year" in droughts
    if droughts["count"]:
        assert droughts["per_year"] < 100, (
            f"{droughts['per_year']}/yr suggests the diurnal cycle is being counted"
        )
        assert droughts["duration_quantiles"]["p50"] >= patterns.MIN_DROUGHT_DAYS


def test_drought_runs_are_internally_consistent(sa1):
    for run in sa1["droughts"].get("worst", []):
        assert run["days"] >= patterns.MIN_DROUGHT_DAYS
        assert run["from_date"] <= run["to_date"]
        assert 0 <= run["mean_renewable_share"] < patterns.DROUGHT_THRESHOLD * 1.5


# ----------------------------------------------------------------- storage sizing


def test_storage_capture_rises_with_size(sa1):
    """More energy must capture more surplus. A non-monotone curve means the simulation
    is not conserving state of charge across hours."""
    curve = sa1["storage"].get("curve", [])
    if len(curve) < 2:
        pytest.skip("no storage curve")
    sizes = [c["energy_mwh"] for c in curve]
    captured = [c["captured_share"] for c in curve]
    assert sizes == sorted(sizes)
    assert all(b >= a - 1e-9 for a, b in zip(captured, captured[1:], strict=False))
    assert all(0 <= c <= 1 for c in captured)


def test_storage_simulation_respects_energy_and_power():
    """A battery cannot absorb more than it can hold, however much surplus arrives."""
    surplus = np.full(48, 1000.0)
    deficit = np.zeros(48)
    captured = patterns._simulate(surplus, deficit, energy_mwh=100.0, power_mw=50.0)
    # With no deficit it can never discharge, so it fills once and stops.
    assert captured <= 100.0 / (patterns.STORAGE_EFFICIENCY**0.5) + 1e-6


def test_storage_discharges_and_refills_when_there_is_demand():
    surplus = np.array([100.0, 0.0] * 24)
    deficit = np.array([0.0, 100.0] * 24)
    captured = patterns._simulate(surplus, deficit, energy_mwh=100.0, power_mw=100.0)
    assert captured > 100.0, "a cycling battery should absorb more than its own capacity"


# ----------------------------------------------------------------- grids


def test_grids_are_twelve_by_twentyfour(sa1):
    for name, grid in sa1["grids"].items():
        assert len(grid) == 12, f"{name}: {len(grid)} months"
        assert all(len(row) == 24 for row in grid), f"{name}: not 24 hours wide"


def test_seasonal_is_measured_not_modelled(sa1):
    """No forecast is involved, and the payload must say so - a recurring pattern is a
    property of the record, and a model in front of it would only add error."""
    assert sa1["data_mode"] == "measured"
    assert sa1["years_of_history"] >= 1.0


# ----------------------------------------------------------------- endpoints


def test_every_endpoint_answers(client):
    for path in ("/health", "/sites", "/regions", "/vss"):
        assert client.get(path).status_code == 200, path


def test_seasonal_endpoint(client, sa1):
    body = client.get("/seasonal/SA1").json()
    assert body["region"] == "SA1"
    assert body["data_mode"] == "measured"
    assert client.get("/seasonal/sa1").status_code == 200, "region should be case-insensitive"
    assert client.get("/seasonal/NOWHERE").status_code == 404


def test_demand_endpoint_agrees_with_balance(client):
    """Demand comes from the balance ensemble, so the two must describe the same draws."""
    if not (get_settings().data_canonical / "balance_SA1.json").exists():
        pytest.skip("no balance window")
    demand = client.get("/demand/SA1").json()
    balance = client.post("/balance", json={"region": "SA1"}).json()

    assert demand["issue_time_utc"] == balance["issue_time_utc"]
    assert len(demand["p50_mw"]) == len(balance["points"])
    for lo, mid, hi in zip(demand["p10_mw"], demand["p50_mw"], demand["p90_mw"], strict=True):
        assert lo <= mid <= hi


def test_dispatch_returns_a_feasible_schedule(client):
    if not (get_settings().data_canonical / "ensemble_SA1.npz").exists():
        pytest.skip("no scenario ensemble")
    body = client.post(
        "/storage/dispatch", json={"region": "SA1", "energy_mwh": 200, "power_mw": 100}
    ).json()

    schedule = body["schedule"]
    power = body["asset"]["power_mw"]
    assert schedule, "empty schedule"
    assert all(r["charge"] <= power + 1e-6 for r in schedule)
    assert all(r["discharge"] <= power + 1e-6 for r in schedule)
    assert not any(r["charge"] > 1e-6 and r["discharge"] > 1e-6 for r in schedule)
    assert all(r["grid_import"] <= body["grid"]["import_limit_mw"] + 1e-6 for r in schedule)
    assert all(r["dispatchable"] <= body["dispatchable_headroom_mw"] + 1e-6 for r in schedule)
    assert body["committed"]["action"] in {"charge", "discharge", "idle"}


def test_a_bigger_battery_never_costs_more(client):
    """Storage is optional, so the optimiser can always ignore extra capacity."""
    if not (get_settings().data_canonical / "ensemble_SA1.npz").exists():
        pytest.skip("no scenario ensemble")
    small = client.post(
        "/storage/dispatch", json={"region": "SA1", "energy_mwh": 100, "power_mw": 50}
    ).json()["expected_cost_aud"]
    large = client.post(
        "/storage/dispatch", json={"region": "SA1", "energy_mwh": 800, "power_mw": 400}
    ).json()["expected_cost_aud"]
    assert large <= small + 1.0, f"800 MWh cost {large} against {small} for 100 MWh"


def test_dispatch_rejects_impossible_batteries(client):
    for body in ({"region": "SA1", "energy_mwh": 0}, {"region": "SA1", "efficiency": 2.0}):
        assert client.post("/storage/dispatch", json=body).status_code == 422
    assert client.post("/storage/dispatch", json={"region": "NOWHERE"}).status_code == 404
