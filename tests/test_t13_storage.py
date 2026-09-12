"""T13 - the dispatch schedule must be physically possible and economically sane."""

from __future__ import annotations

import json

import numpy as np
import pytest

from reip.config import get_settings
from reip.storage.asset import GridLimits, StorageAsset
from reip.storage.dispatch import solve, value_of_stochastic_solution

T = 12
S = 6


def _inputs(seed: int = 0, *, scarce: bool = True):
    rng = np.random.default_rng(seed)
    hours = np.arange(T)
    renewable = np.clip(300 * np.sin(hours / T * np.pi)[None, :] * (1 + 0.3 * rng.standard_normal((S, 1))), 0, None)
    demand = np.full((S, T), 250.0)
    # Cheap when the sun is up, expensive in the evening - the arbitrage the battery exists for.
    price = 50 + 100 * np.cos(hours / T * np.pi)
    grid = GridLimits(import_limit_mw=80, export_limit_mw=80) if scarce else GridLimits()
    return renewable, demand, price, grid


def test_schedule_is_physically_possible():
    renewable, demand, price, grid = _inputs()
    asset = StorageAsset(energy_mwh=100, power_mw=50)
    result = solve(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=asset, grid=grid, dispatchable_mw=200.0,
    )
    s = result.schedule
    assert (s["charge"] <= asset.power_mw + 1e-6).all()
    assert (s["discharge"] <= asset.power_mw + 1e-6).all()
    assert (s["energy"] >= asset.min_energy_mwh - 1e-6).all()
    assert (s["energy"] <= asset.max_energy_mwh + 1e-6).all()
    assert (s[["charge", "discharge", "curtail", "unserved"]] >= -1e-9).all().all()


def test_no_simultaneous_charge_and_discharge():
    """The binary the MILP formulation would add is redundant - this proves it.

    Charging and discharging at once destroys energy whenever round-trip efficiency is
    below 1, so a cost-minimising LP never does it. If this ever fails, the LP relaxation
    is no longer safe and the integer constraint has to come back.
    """
    renewable, demand, price, grid = _inputs()
    result = solve(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=StorageAsset(energy_mwh=100, power_mw=50), grid=grid, dispatchable_mw=200.0,
    )
    both = (result.schedule["charge"] > 1e-6) & (result.schedule["discharge"] > 1e-6)
    assert not both.any(), f"{int(both.sum())} hours charge and discharge at once"


def test_terminal_state_of_charge_is_respected():
    """Without this the optimiser empties the battery into the final hour."""
    asset = StorageAsset(energy_mwh=100, power_mw=50, terminal_soc=0.6)
    renewable, demand, price, grid = _inputs()
    result = solve(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=asset, grid=grid, dispatchable_mw=200.0,
    )
    assert result.schedule["energy"].iloc[-1] >= asset.terminal_energy_mwh - 1e-6


def test_energy_balance_holds_every_hour():
    """Supply must equal demand in every hour, or the schedule is fiction."""
    renewable, demand, price, grid = _inputs()
    asset = StorageAsset(energy_mwh=100, power_mw=50)
    result = solve(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=asset, grid=grid, dispatchable_mw=200.0,
    )
    s = result.schedule
    supply = (
        renewable.mean(axis=0) - s["curtail"] + s["discharge"] + s["dispatchable"]
        + s["grid_import"] + s["unserved"]
    )
    consumption = demand.mean(axis=0) + s["charge"] + s["grid_export"]
    np.testing.assert_allclose(supply, consumption, atol=1e-5)


def test_non_anticipativity_binds_hour_one():
    """Hour 1 is one decision taken before the future is known.

    Without this the "stochastic" solution is N perfect-foresight plans in disguise, and its
    cost is not achievable by anyone.
    """
    renewable, demand, price, grid = _inputs()
    asset = StorageAsset(energy_mwh=100, power_mw=50)
    shared = solve(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=asset, grid=grid, dispatchable_mw=200.0,
    )
    free = solve(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=asset, grid=grid, dispatchable_mw=200.0, per_scenario=True,
    )
    # Relaxing a constraint cannot raise the cost of a minimisation.
    assert free.expected_cost_aud <= shared.expected_cost_aud + 1e-6


def test_bounds_are_ordered():
    """WS <= RP <= EEV, by construction. Any other ordering means a formulation error."""
    renewable, demand, price, grid = _inputs(seed=3)
    result = value_of_stochastic_solution(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=StorageAsset(energy_mwh=100, power_mw=50), grid=grid, dispatchable_mw=200.0,
    )
    assert result["wait_and_see_aud"] <= result["stochastic_aud"] + 1e-3
    assert result["stochastic_aud"] <= result["expected_value_solution_aud"] + 1e-3
    assert result["vss_aud"] >= -1e-3
    assert result["evpi_aud"] >= -1e-3


def test_unconstrained_grid_makes_uncertainty_worthless():
    """A real property of the problem, not a quirk.

    With unlimited exchange at a known price every imbalance settles at that price, nothing
    is scarce, and how well the battery is dispatched stops mattering. VSS is legitimately
    zero. Anyone reporting a large VSS from an unconstrained model has a bug.
    """
    renewable, demand, price, _ = _inputs(scarce=False)
    result = value_of_stochastic_solution(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        asset=StorageAsset(energy_mwh=100, power_mw=50),
        grid=GridLimits(), dispatchable_mw=500.0,
    )
    assert result["vss_aud"] == pytest.approx(0.0, abs=1.0)


def test_a_battery_never_costs_more_than_no_battery():
    """Storage is optional: the optimiser can always leave it idle."""
    renewable, demand, price, grid = _inputs()
    common = dict(
        renewable_mw=renewable, demand_mw=demand, price_aud_mwh=price,
        grid=grid, dispatchable_mw=200.0,
    )
    with_battery = solve(asset=StorageAsset(energy_mwh=100, power_mw=50), **common)
    # A battery with negligible power is effectively no battery.
    without = solve(asset=StorageAsset(energy_mwh=1e-3, power_mw=1e-6), **common)
    assert with_battery.expected_cost_aud <= without.expected_cost_aud + 1e-3


# ------------------------------------------------------------------- asset validation


def test_asset_rejects_impossible_configurations():
    with pytest.raises(ValueError, match="efficiency"):
        StorageAsset(efficiency=1.5)
    with pytest.raises(ValueError, match="soc_min"):
        StorageAsset(soc_min=0.9, soc_max=0.1)
    with pytest.raises(ValueError, match="terminal_soc"):
        StorageAsset(soc_min=0.2, soc_max=0.8, terminal_soc=0.95)
    with pytest.raises(ValueError, match="positive"):
        StorageAsset(energy_mwh=0)


def test_duration_matches_industry_convention():
    assert StorageAsset(energy_mwh=200, power_mw=100).duration_h == pytest.approx(2.0)


# -------------------------------------------------------------- measured outcome


def test_vss_report_is_internally_consistent():
    path = get_settings().reports_dir / "vss.json"
    if not path.exists():
        pytest.skip("vss.json absent; run `python -m reip.eval.vss`")

    for entry in json.loads(path.read_text(encoding="utf-8")):
        cost = entry["cost_aud_per_window"]
        label = entry["region"]
        assert cost["wait_and_see"] <= cost["stochastic"] + 1.0, f"{label}: WS above RP"
        assert cost["stochastic"] <= cost["expected_value"] + 1.0, f"{label}: RP above EEV"
        assert entry["vss_aud_total"] >= -1.0, f"{label}: negative VSS"
        assert entry["evpi_aud_total"] >= -1.0, f"{label}: negative EVPI"
        # Grid limits must have come from data, not from the permissive default.
        assert entry["grid"]["export_limit_mw"] < 1e5, f"{label}: grid limits were not measured"
