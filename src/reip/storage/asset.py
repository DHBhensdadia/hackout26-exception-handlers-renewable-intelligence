"""The storage asset, and the grid it sits behind.

Configurable rather than learned. No per-plant storage data is public - AEMO's
`BDU_INITIAL_ENERGY_STORAGE` gives a regional aggregate and only from mid-2025 - and a
planning tool needs to answer "what would a 200 MWh battery do here?" for batteries that do
not exist yet. A fitted model could not answer that question at all.

Defaults describe a utility-scale lithium battery of the kind actually being built on the
NEM: two hours of storage at rated power, round-trip efficiency in the high eighties.
"""

from __future__ import annotations

from dataclasses import dataclass

# Round-trip efficiency is split evenly between charging and discharging. The physical
# split differs slightly in reality, but only the product affects the energy accounting and
# no public data distinguishes the two halves per asset.
DEFAULT_EFFICIENCY: float = 0.88

# Value of lost load, AUD/MWh. The AEMO market price cap, which is the regulator's own
# statement of what unserved energy is worth - so unserved energy is never the cheap option
# and the optimiser will exhaust every alternative first.
VOLL_AUD_MWH: float = 20_000.0

# A small per-MWh throughput cost, standing in for cycle degradation. Without it the LP is
# indifferent to churning the battery back and forth at equal prices, and returns schedules
# that cycle for no gain.
DEGRADATION_AUD_MWH: float = 2.0

# Curtailment carries no direct cost, but zero cost makes it a free slack variable that the
# solver will use to avoid arithmetic it should be doing. A token price keeps it honest
# without distorting the economics.
CURTAILMENT_PENALTY_AUD_MWH: float = 0.01


@dataclass(frozen=True)
class StorageAsset:
    """A battery, described by what actually constrains its dispatch."""

    energy_mwh: float = 200.0
    power_mw: float = 100.0
    efficiency: float = DEFAULT_EFFICIENCY
    soc_min: float = 0.05
    soc_max: float = 0.95
    initial_soc: float = 0.5

    # State of charge required at the end of the horizon, as a fraction.
    #
    # Not optional. With a free horizon end the optimiser empties the battery into hour 72
    # because nothing after that point exists to reward keeping charge - an artefact of
    # where the window stops, not a recommendation anyone should act on. Anchoring the end
    # near the start makes the schedule a repeatable daily policy rather than a one-off
    # liquidation.
    terminal_soc: float = 0.5

    def __post_init__(self) -> None:
        if not 0 < self.efficiency <= 1:
            raise ValueError("efficiency must be in (0, 1]")
        if not 0 <= self.soc_min < self.soc_max <= 1:
            raise ValueError("soc_min must be below soc_max, both within [0, 1]")
        for name in ("initial_soc", "terminal_soc"):
            value = getattr(self, name)
            if not self.soc_min <= value <= self.soc_max:
                raise ValueError(f"{name} {value} lies outside [{self.soc_min}, {self.soc_max}]")
        if self.energy_mwh <= 0 or self.power_mw <= 0:
            raise ValueError("energy_mwh and power_mw must be positive")

    @property
    def charge_efficiency(self) -> float:
        return self.efficiency**0.5

    @property
    def discharge_efficiency(self) -> float:
        return self.efficiency**0.5

    @property
    def min_energy_mwh(self) -> float:
        return self.soc_min * self.energy_mwh

    @property
    def max_energy_mwh(self) -> float:
        return self.soc_max * self.energy_mwh

    @property
    def initial_energy_mwh(self) -> float:
        return self.initial_soc * self.energy_mwh

    @property
    def terminal_energy_mwh(self) -> float:
        return self.terminal_soc * self.energy_mwh

    @property
    def duration_h(self) -> float:
        """Hours at rated power - how the industry actually describes a battery."""
        return self.energy_mwh / self.power_mw


@dataclass(frozen=True)
class GridLimits:
    """What the region can exchange with the rest of the network.

    A region is not an island: surplus that leaves over an interconnector is exported, not
    curtailed, and a shortfall that arrives over one is imported, not unserved. Ignoring
    the wires would make both look far worse than they are.

    Defaults are deliberately generous so the balance is driven by the battery and the
    forecast rather than by an invented transmission constraint. Set them from
    `NETINTERCHANGE` when modelling a specific region.
    """

    import_limit_mw: float = 1e6
    export_limit_mw: float = 1e6


def grid_limits_from_market(region: str, market=None, *, quantile: float = 0.99) -> GridLimits:
    """Interconnector capability inferred from what the region has actually exchanged.

    `NETINTERCHANGE` records the flow in and out of a region every five minutes over three
    years, so the extremes of that record are a better statement of what the wires can carry
    than any number this project would otherwise have to invent. A high quantile rather than
    the maximum, since the maximum picks up single intervals that no planner would rely on.

    This matters more than it looks. With unlimited exchange, any imbalance is resolved by
    importing or exporting at the spot price, nothing is ever scarce, and the value of
    planning against uncertainty is exactly zero. Scarcity is what makes a battery worth
    dispatching well, and the wires are what create it.
    """
    import pandas as pd

    from reip.config import get_settings

    if market is None:
        market = pd.read_parquet(get_settings().data_canonical / "aemo_market.parquet")

    block = market[market["region"] == region]
    if block.empty or "net_interchange_mw" not in block.columns:
        return GridLimits()

    flow = block["net_interchange_mw"].dropna()
    if flow.empty:
        return GridLimits()

    # Sign convention: positive is net export out of the region.
    export = float(max(flow.quantile(quantile), 0.0))
    imported = float(max(-flow.quantile(1 - quantile), 0.0))
    return GridLimits(
        import_limit_mw=imported or 1e6,
        export_limit_mw=export or 1e6,
    )
