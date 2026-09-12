"""Two-stage stochastic dispatch of storage against a scenario ensemble.

Hour 1 is a here-and-now commitment: one decision, taken before anyone knows which future
arrives, and identical across every scenario. Hours 2 onward are recourse - the schedule is
allowed to differ per scenario because by then more will be known. That asymmetry is the
whole point of a two-stage program, and it is enforced by the non-anticipativity
constraints below rather than assumed.

**An LP, not a MILP.** The textbook formulation adds a binary per hour to forbid charging
and discharging at once. It is redundant whenever round-trip efficiency is below 1:
doing both simultaneously destroys energy and costs money, so no cost-minimising solution
ever wants to. Dropping it turns a problem that would take minutes into one that takes
seconds, with no loss of correctness. The property is asserted in the tests rather than
trusted.

**Why not dispatch against a p50 forecast.** A battery's state of charge at hour 30 depends
on what happened in hours 1-29, so the decision is path-dependent and a per-hour quantile
cannot express a path. Dispatching on the median commits to one future and is caught out by
every other one. Measuring exactly how much that costs is what `value_of_stochastic_solution`
does, and it is the number that justifies the entire uncertainty chain behind it.

Variables, per scenario `s` and hour `t`, all non-negative:

    charge, discharge     battery power, MW
    dispatchable          output from the non-renewable fleet, MW
    grid_import           drawn from the rest of the network, MW
    grid_export           sent to it, MW
    curtail               renewable output spilled, MW
    unserved              demand not met, MW
    energy                state of charge at the end of the hour, MWh
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog

from reip.storage.asset import (
    CURTAILMENT_PENALTY_AUD_MWH,
    DEGRADATION_AUD_MWH,
    VOLL_AUD_MWH,
    GridLimits,
    StorageAsset,
)

log = logging.getLogger(__name__)

# Variables per (scenario, hour), in the order they are laid out in the solution vector.
FIELDS = (
    "charge",
    "discharge",
    "dispatchable",
    "grid_import",
    "grid_export",
    "curtail",
    "unserved",
    "energy",
)
N_FIELDS = len(FIELDS)


@dataclass(frozen=True)
class DispatchResult:
    """A schedule, its cost, and the one decision that is actually being committed to."""

    schedule: pd.DataFrame
    expected_cost_aud: float
    committed_charge_mw: float
    committed_discharge_mw: float
    n_scenarios: int
    status: str

    @property
    def committed_action(self) -> str:
        net = self.committed_discharge_mw - self.committed_charge_mw
        if net > 1e-6:
            return "discharge"
        if net < -1e-6:
            return "charge"
        return "idle"


def _index(scenario: int, hour: int, field: int, n_hours: int) -> int:
    return (scenario * n_hours + hour) * N_FIELDS + field


def solve(
    *,
    renewable_mw: np.ndarray,
    demand_mw: np.ndarray,
    price_aud_mwh: np.ndarray,
    asset: StorageAsset,
    grid: GridLimits | None = None,
    dispatchable_mw: float = 0.0,
    fix_first_stage: tuple[float, float] | None = None,
    per_scenario: bool = False,
) -> DispatchResult:
    """Minimise expected cost over a `(scenario, hour)` ensemble.

    `renewable_mw` and `demand_mw` are `(scenario, hour)`. `price_aud_mwh` is per hour and
    shared - the spot price is a market outcome, and treating it as certain while generation
    is uncertain is a deliberate simplification, stated rather than hidden.

    `fix_first_stage` pins hour 1 to a given (charge, discharge), which is how the
    expected-value policy is evaluated fairly against the stochastic one.

    `dispatchable_mw` is the non-renewable fleet's available headroom. Without it a region
    appears to be short by its entire conventional generation every hour: NSW1 came out at
    8 billion AUD per 72 hours, which is 4.3 GW of unserved load priced at VOLL, and is
    simply the coal fleet missing from the model rather than anything the grid does.

    `per_scenario=True` drops non-anticipativity entirely, letting every scenario choose its
    own hour 1. That is the wait-and-see bound: what a perfect forecast would be worth. It
    is not achievable, and is computed only as a reference.
    """
    grid = grid or GridLimits()
    renewable_mw = np.atleast_2d(renewable_mw)
    demand_mw = np.atleast_2d(demand_mw)
    n_scenarios, n_hours = renewable_mw.shape
    if demand_mw.shape != (n_scenarios, n_hours):
        raise ValueError("renewable and demand ensembles disagree on shape")
    if len(price_aud_mwh) != n_hours:
        raise ValueError("price series length does not match the horizon")

    n_vars = n_scenarios * n_hours * N_FIELDS
    weight = 1.0 / n_scenarios

    # --- objective ------------------------------------------------------------------
    cost = np.zeros(n_vars)
    for s in range(n_scenarios):
        for t in range(n_hours):
            base = (s * n_hours + t) * N_FIELDS
            price = float(price_aud_mwh[t])
            cost[base + 0] = weight * DEGRADATION_AUD_MWH  # charge
            cost[base + 1] = weight * DEGRADATION_AUD_MWH  # discharge
            # The conventional fleet is the marginal plant in most hours, so the spot price
            # is what running it costs the region. Pricing it below spot would make the
            # battery pointless; above spot would make it never run.
            cost[base + 2] = weight * price  # dispatchable
            cost[base + 3] = weight * price  # import costs
            cost[base + 4] = -weight * price  # export earns
            cost[base + 5] = weight * CURTAILMENT_PENALTY_AUD_MWH
            cost[base + 6] = weight * VOLL_AUD_MWH

    # --- bounds ---------------------------------------------------------------------
    lower = np.zeros(n_vars)
    upper = np.full(n_vars, np.inf)
    for s in range(n_scenarios):
        for t in range(n_hours):
            base = (s * n_hours + t) * N_FIELDS
            upper[base + 0] = asset.power_mw
            upper[base + 1] = asset.power_mw
            upper[base + 2] = max(dispatchable_mw, 0.0)
            upper[base + 3] = grid.import_limit_mw
            upper[base + 4] = grid.export_limit_mw
            # Only generation that exists can be spilled.
            upper[base + 5] = max(float(renewable_mw[s, t]), 0.0)
            lower[base + 7] = asset.min_energy_mwh
            upper[base + 7] = asset.max_energy_mwh

    rows, cols, data, rhs = [], [], [], []
    row = 0

    def add(entries: list[tuple[int, float]], value: float) -> None:
        nonlocal row
        for column, coefficient in entries:
            rows.append(row)
            cols.append(column)
            data.append(coefficient)
        rhs.append(value)
        row += 1

    # --- energy balance, per scenario-hour ------------------------------------------
    # renewable - curtail + discharge + import + unserved = demand + charge + export
    for s in range(n_scenarios):
        for t in range(n_hours):
            base = (s * n_hours + t) * N_FIELDS
            add(
                [
                    (base + 0, -1.0),  # charge consumes
                    (base + 1, +1.0),  # discharge supplies
                    (base + 2, +1.0),  # dispatchable supplies
                    (base + 3, +1.0),  # import supplies
                    (base + 4, -1.0),  # export consumes
                    (base + 5, -1.0),  # curtailment removes generation
                    (base + 6, +1.0),  # unserved is demand given up
                ],
                float(demand_mw[s, t] - renewable_mw[s, t]),
            )

    # --- state of charge ------------------------------------------------------------
    eta_c, eta_d = asset.charge_efficiency, asset.discharge_efficiency
    for s in range(n_scenarios):
        for t in range(n_hours):
            base = (s * n_hours + t) * N_FIELDS
            entries = [(base + 7, 1.0), (base + 0, -eta_c), (base + 1, 1.0 / eta_d)]
            if t == 0:
                add(entries, asset.initial_energy_mwh)
            else:
                previous = ((s * n_hours + t - 1) * N_FIELDS) + 7
                add([*entries, (previous, -1.0)], 0.0)

    # --- non-anticipativity ----------------------------------------------------------
    # Hour 1 cannot depend on which scenario materialises, because at the moment it is
    # taken nobody knows. Without these rows the "stochastic" solution is 200 separate
    # perfect-foresight plans wearing a trench coat, and its cost is not achievable.
    if not per_scenario:
        for s in range(1, n_scenarios):
            for field in (0, 1):
                add(
                    [
                        (_index(s, 0, field, n_hours), 1.0),
                        (_index(0, 0, field, n_hours), -1.0),
                    ],
                    0.0,
                )

    if fix_first_stage is not None:
        for field, value in enumerate(fix_first_stage):
            add([(_index(0, 0, field, n_hours), 1.0)], float(value))

    A_eq = sparse.csr_matrix(
        (data, (rows, cols)), shape=(row, n_vars)
    )
    b_eq = np.array(rhs)

    # --- terminal state of charge ----------------------------------------------------
    ub_rows, ub_cols, ub_data, ub_rhs = [], [], [], []
    for s in range(n_scenarios):
        ub_rows.append(s)
        ub_cols.append(_index(s, n_hours - 1, 7, n_hours))
        ub_data.append(-1.0)
        ub_rhs.append(-asset.terminal_energy_mwh)
    A_ub = sparse.csr_matrix((ub_data, (ub_rows, ub_cols)), shape=(n_scenarios, n_vars))

    result = linprog(
        cost,
        A_ub=A_ub,
        b_ub=np.array(ub_rhs),
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=np.column_stack([lower, upper]),
        method="highs",
    )
    if not result.success:
        raise RuntimeError(f"dispatch LP did not solve: {result.message}")

    values = result.x.reshape(n_scenarios, n_hours, N_FIELDS)
    schedule = pd.DataFrame(
        {
            "hour": np.arange(n_hours),
            **{
                name: values[:, :, i].mean(axis=0)
                for i, name in enumerate(FIELDS)
            },
        }
    )
    schedule["soc_fraction"] = schedule["energy"] / asset.energy_mwh
    schedule["net_battery_mw"] = schedule["discharge"] - schedule["charge"]

    return DispatchResult(
        schedule=schedule,
        expected_cost_aud=float(result.fun),
        committed_charge_mw=float(values[0, 0, 0]),
        committed_discharge_mw=float(values[0, 0, 1]),
        n_scenarios=n_scenarios,
        status=str(result.message),
    )


def value_of_stochastic_solution(
    *,
    renewable_mw: np.ndarray,
    demand_mw: np.ndarray,
    price_aud_mwh: np.ndarray,
    asset: StorageAsset,
    grid: GridLimits | None = None,
    dispatchable_mw: float = 0.0,
) -> dict:
    """What planning against the full ensemble is worth, against planning on the median.

    Three quantities, in the standard stochastic-programming sense:

    * **WS**, wait-and-see - every scenario solved with perfect foresight, then averaged. A
      lower bound nobody can reach; it assumes the future is known in advance.
    * **RP**, recourse problem - the two-stage stochastic solution. Achievable.
    * **EEV**, expected result of the expected-value solution - take the hour-1 decision the
      *median* forecast recommends, then let each scenario do the best it can afterwards.
      This is what dispatching on a point forecast actually costs.

    `VSS = EEV - RP` is what the uncertainty band is worth in dollars. `EVPI = RP - WS` is
    the headroom a perfect forecast would still unlock, which bounds how much any further
    modelling could ever gain.
    """
    grid = grid or GridLimits()
    common = {
        "price_aud_mwh": price_aud_mwh,
        "asset": asset,
        "grid": grid,
        "dispatchable_mw": dispatchable_mw,
    }

    stochastic = solve(renewable_mw=renewable_mw, demand_mw=demand_mw, **common)

    wait_and_see = solve(
        renewable_mw=renewable_mw, demand_mw=demand_mw, per_scenario=True, **common
    )

    # The expected-value problem: one scenario, built from the median of each hour.
    median_renewable = np.median(renewable_mw, axis=0, keepdims=True)
    median_demand = np.median(demand_mw, axis=0, keepdims=True)
    deterministic = solve(renewable_mw=median_renewable, demand_mw=median_demand, **common)

    # Its hour-1 decision, imposed on the real ensemble.
    eev = solve(
        renewable_mw=renewable_mw,
        demand_mw=demand_mw,
        fix_first_stage=(
            deterministic.committed_charge_mw,
            deterministic.committed_discharge_mw,
        ),
        **common,
    )

    vss = eev.expected_cost_aud - stochastic.expected_cost_aud
    evpi = stochastic.expected_cost_aud - wait_and_see.expected_cost_aud

    log.info(
        "WS %.0f <= RP %.0f <= EEV %.0f AUD | VSS %+.0f | EVPI %+.0f",
        wait_and_see.expected_cost_aud,
        stochastic.expected_cost_aud,
        eev.expected_cost_aud,
        vss,
        evpi,
    )
    return {
        "wait_and_see_aud": round(wait_and_see.expected_cost_aud, 2),
        "stochastic_aud": round(stochastic.expected_cost_aud, 2),
        "expected_value_solution_aud": round(eev.expected_cost_aud, 2),
        "vss_aud": round(vss, 2),
        "evpi_aud": round(evpi, 2),
        "n_scenarios": int(np.atleast_2d(renewable_mw).shape[0]),
        "horizon_h": int(np.atleast_2d(renewable_mw).shape[1]),
        "committed_action": stochastic.committed_action,
        "deterministic_committed_action": deterministic.committed_action,
    }
