"""T9 - the market corpus must line up with the generation corpus.

Demand, price and rooftop PV arrive from the same MMSDM archive as the SCADA but on
different intervals - 5 minutes for dispatch, 30 for rooftop - and with a settlement stamp
that labels the end of its interval in a timezone (UTC+10, no daylight saving) that is not
the local time of any state for half the year.

Every one of those is silent when wrong. The data still parses, still aggregates, and
simply describes the wrong hour. A one-hour shift between demand and generation would make
the balance module wrong in a way no amount of downstream care could recover, so the checks
here are on physical signatures rather than on row counts.
"""

from __future__ import annotations

import pytest

from reip.ingest.aemo_market import DEMAND_BOUNDS_MW, NEM_REGIONS, RRP_BOUNDS

# South Australia has the highest rooftop-PV penetration of any NEM region, so its demand
# curve is the one where the midday trough is unmistakable rather than merely present.
DUCK_CURVE_REGION = "SA1"


def test_no_duplicate_region_hours(market):
    """One row per region per hour. Intervention runs are the usual cause of duplicates."""
    dupes = market.duplicated(subset=["region", "valid_time_utc"]).sum()
    assert dupes == 0, f"{dupes} duplicate (region, hour) rows - INTERVENTION filter may have failed"


def test_timestamps_are_utc_and_ordered(market):
    assert market["valid_time_utc"].dt.tz is not None, "valid_time_utc is not timezone-aware"
    for region, block in market.groupby("region"):
        times = block["valid_time_utc"]
        assert times.is_monotonic_increasing, f"{region}: timestamps not ordered"


def test_all_regions_present(market):
    missing = set(NEM_REGIONS) - set(market["region"].unique())
    assert not missing, f"missing regions: {sorted(missing)}"


def test_demand_is_physically_plausible(market):
    lo, hi = DEMAND_BOUNDS_MW
    demand = market["demand_mw"].dropna()
    assert demand.between(lo, hi).all(), (
        f"demand outside [{lo}, {hi}] MW - likely the wrong column was read: "
        f"min {demand.min():.0f}, max {demand.max():.0f}"
    )


def test_price_within_market_bounds(market):
    """RRP genuinely reaches the cap and the floor; outside them means a parsing error."""
    lo, hi = RRP_BOUNDS
    rrp = market["rrp_aud_mwh"].dropna()
    assert rrp.between(lo, hi).all(), f"RRP outside [{lo}, {hi}]"
    # Negative prices are not an anomaly in a high-renewable market - they are the state
    # the surplus logic exists to anticipate. If none appear, the join has gone wrong.
    assert (rrp < 0).any(), "no negative prices anywhere in three years, which is implausible"


def test_rooftop_pv_follows_the_sun(market):
    """The timezone proof.

    Rooftop PV is the one series whose correct shape is known a priori: exactly zero at
    night, peaking near local solar noon. If the market-time conversion were wrong by even
    an hour this would show up as generation before sunrise, and no other check in the
    suite would catch it.
    """
    block = market[market["region"] == DUCK_CURVE_REGION].dropna(subset=["rooftop_pv_mw"])
    if block.empty:
        pytest.skip("no rooftop PV for the reference region")

    local = block["valid_time_utc"].dt.tz_convert("Australia/Adelaide")
    profile = block.groupby(local.dt.hour)["rooftop_pv_mw"].mean()

    assert profile.loc[0:3].max() == 0, "rooftop PV is generating after midnight"
    assert profile.loc[21:23].max() == 0, "rooftop PV is generating late at night"
    assert 9 <= profile.idxmax() <= 14, (
        f"rooftop PV peaks at local hour {profile.idxmax()}, not near solar noon - "
        "the market-time conversion is off"
    )


def test_demand_trough_is_at_midday(market):
    """The duck curve. Operational demand is net of rooftop PV, so a high-penetration
    region dips at midday and peaks after sunset - the inverse of a naive load curve."""
    block = market[market["region"] == DUCK_CURVE_REGION]
    local = block["valid_time_utc"].dt.tz_convert("Australia/Adelaide")
    profile = block.groupby(local.dt.hour)["demand_mw"].mean()

    assert 10 <= profile.idxmin() <= 15, (
        f"demand trough at local hour {profile.idxmin()}, expected midday"
    )
    assert 16 <= profile.idxmax() <= 21, (
        f"demand peak at local hour {profile.idxmax()}, expected evening"
    )


def test_curtailment_is_non_negative_and_bounded(market):
    """Curtailment is UIGF minus cleared. It cannot be negative, and cannot exceed UIGF."""
    for tech in ("solar", "wind"):
        block = market.dropna(subset=[f"{tech}_uigf_mw", f"{tech}_cleared_mw"])
        if block.empty:
            continue
        curtailed = block[f"{tech}_curtailed_mw"]
        assert (curtailed >= 0).all(), f"{tech}: negative curtailment"
        assert (curtailed <= block[f"{tech}_uigf_mw"] + 1e-6).all(), (
            f"{tech}: curtailment exceeds available generation"
        )


def test_market_and_generation_corpora_overlap(market, solar_power):
    """The two halves must describe the same period, or the balance has nothing to balance."""
    m_lo, m_hi = market["valid_time_utc"].min(), market["valid_time_utc"].max()
    g_lo, g_hi = solar_power["valid_time_utc"].min(), solar_power["valid_time_utc"].max()

    overlap = min(m_hi, g_hi) - max(m_lo, g_lo)
    assert overlap.days > 300, (
        f"market ({m_lo:%Y-%m-%d} to {m_hi:%Y-%m-%d}) and generation "
        f"({g_lo:%Y-%m-%d} to {g_hi:%Y-%m-%d}) overlap by only {overlap.days} days"
    )
