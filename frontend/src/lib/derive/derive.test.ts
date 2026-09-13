import { describe, expect, it } from "vitest";
import type { ForecastResponse, HourPoint, RegionRecord, SiteRecord } from "@/types";
import {
  computeBalance,
  demandBand,
  hash01,
  invariantViolations,
  investmentScenarios,
  reliabilityModel,
  seasonalCells,
  storageModel,
  summarizeDemand,
  summarizeSeasonal,
} from "./index";

const site: SiteRecord = {
  site_id: "GJ-SOLAR-TEST",
  name: "Test Solar",
  latitude: 23.03,
  longitude: 72.57,
  tech: "solar",
  capacity_mw: 50,
  region: "Gujarat",
  in_training_data: true,
};

function makeForecast(hours = 24): ForecastResponse {
  const points: HourPoint[] = Array.from({ length: hours }, (_, i) => ({
    valid_time_utc: new Date(Date.UTC(2026, 0, 1, i)).toISOString(),
    horizon_h: i + 1,
    p10_mw: 4,
    p50_mw: 10,
    p90_mw: 16,
    clearsky_mw: 18,
    physics_mw: 17,
  }));
  return {
    site_id: site.site_id,
    tech: "solar",
    issue_time_utc: new Date(Date.UTC(2026, 0, 1)).toISOString(),
    capacity_mw: site.capacity_mw,
    model_version: "test",
    weather_source: "test",
    location_is_estimated: false,
    points,
  };
}

describe("hash01", () => {
  it("is deterministic and bounded", () => {
    expect(hash01("abc")).toBe(hash01("abc"));
    expect(hash01("abc")).not.toBe(hash01("abd"));
    expect(hash01("abc")).toBeGreaterThanOrEqual(0);
    expect(hash01("abc")).toBeLessThan(1);
  });
});

describe("storageModel", () => {
  it("scales with site rating and stays consistent", () => {
    const s = storageModel(site);
    expect(s.capacity_mwh).toBeGreaterThan(0);
    expect(s.available_mwh + s.headroom_mwh).toBe(s.capacity_mwh);
    expect(s.soc_pct).toBeGreaterThanOrEqual(45);
    expect(s.soc_pct).toBeLessThanOrEqual(75);
  });
});

describe("computeBalance", () => {
  const forecast = makeForecast(24);
  const storage = storageModel(site);
  const balance = computeBalance(forecast, site, storage);

  it("partitions every hour into surplus or shortage", () => {
    expect(balance.surplusHours + balance.shortageHours).toBe(balance.hours.length);
    expect(balance.hours).toHaveLength(24);
  });

  it("never reports negative energy", () => {
    expect(balance.surplusEnergy).toBeGreaterThanOrEqual(0);
    expect(balance.shortageEnergy).toBeGreaterThanOrEqual(0);
    expect(balance.unmetEnergy).toBeGreaterThanOrEqual(0);
    expect(balance.curtailEnergy).toBeGreaterThanOrEqual(0);
  });

  it("keeps demand-met within 0..100", () => {
    expect(balance.demandMetPct).toBeGreaterThanOrEqual(0);
    expect(balance.demandMetPct).toBeLessThanOrEqual(100);
  });

  it("keeps storage state of charge within [0, capacity]", () => {
    for (const h of balance.hours) {
      expect(h.soc_mwh).toBeGreaterThanOrEqual(0);
      expect(h.soc_mwh).toBeLessThanOrEqual(storage.capacity_mwh);
    }
  });
});

describe("invariantViolations", () => {
  it("passes for well-formed input", () => {
    const forecast = makeForecast(12);
    const balance = computeBalance(forecast, site, storageModel(site));
    expect(invariantViolations(forecast, balance)).toEqual([]);
  });

  it("flags broken quantile ordering", () => {
    const forecast = makeForecast(3);
    forecast.points[1] = { ...forecast.points[1], p10_mw: 99 };
    const balance = computeBalance(forecast, site, storageModel(site));
    expect(invariantViolations(forecast, balance).some((v) => v.includes("quantile order"))).toBe(true);
  });
});

describe("investmentScenarios", () => {
  const scenarios = investmentScenarios(500, site, 70);

  it("allocates the whole budget in every scenario", () => {
    for (const s of scenarios) {
      const sum = s.allocation.reduce((a, x) => a + x.cr, 0);
      expect(Math.abs(sum - s.capex_cr)).toBeLessThanOrEqual(s.capex_cr * 0.02);
    }
  });

  it("recommends exactly one scenario", () => {
    expect(scenarios.filter((s) => s.recommended)).toHaveLength(1);
  });
});

describe("regional demand", () => {
  const region: RegionRecord = {
    region_id: "SA1",
    name: "South Australia",
    nmae_pct: 3.17,
    coverage_pct: 84.6,
    balance_available: true,
    headroom_mw: 1610,
  };
  const issue = new Date(Date.UTC(2026, 0, 1, 0, 0, 0));
  const demand = summarizeDemand(demandBand(region, issue, 72), region, 2026);

  it("keeps p10 <= p50 <= p90 across the horizon", () => {
    expect(demand.points).toHaveLength(72);
    for (const p of demand.points) {
      expect(p.p10_mw).toBeLessThanOrEqual(p.p50_mw);
      expect(p.p50_mw).toBeLessThanOrEqual(p.p90_mw);
      expect(p.p10_mw).toBeGreaterThanOrEqual(0);
    }
  });

  it("carries the region's measured accuracy and a headroom read", () => {
    expect(demand.nmae_pct).toBe(3.17);
    expect(demand.headroom_mw).toBe(1610);
    expect(demand.peak.p50_mw).toBeGreaterThan(0);
    expect(demand.plan.years).toHaveLength(5);
    expect(demand.renewable_band).toHaveLength(72);
  });
});

describe("seasonal grid", () => {
  const region: RegionRecord = {
    region_id: "SA1",
    name: "South Australia",
    nmae_pct: 3.17,
    coverage_pct: 84.6,
    balance_available: true,
    headroom_mw: 1610,
  };
  const grid = summarizeSeasonal(seasonalCells(region));

  it("is exactly 12 x 24 and deterministic", () => {
    expect(grid.cells).toHaveLength(288);
    expect(new Set(grid.cells.map((c) => `${c.month}-${c.hour}`)).size).toBe(288);
    expect(grid.months).toHaveLength(12);
    expect(seasonalCells(region).cells[0].residual_mwh).toBe(grid.cells[0].residual_mwh);
  });

  it("binds surplus share and storage to sane ranges", () => {
    for (const c of grid.cells) {
      expect(c.surplus_pct).toBeGreaterThanOrEqual(0);
      expect(c.surplus_pct).toBeLessThanOrEqual(1);
    }
    expect(grid.storage_to_absorb_mwh).toBeGreaterThanOrEqual(0);
    expect(grid.recurring_surplus_hours).toBeGreaterThanOrEqual(0);
    expect(grid.peak.residual_mwh).toBe(Math.max(...grid.cells.map((c) => c.residual_mwh)));
  });
});

describe("reliabilityModel", () => {
  it("returns a bounded risk score and drivers", () => {
    const r = reliabilityModel(makeForecast(24), site);
    expect(r.risk).toBeGreaterThanOrEqual(0.05);
    expect(r.risk).toBeLessThanOrEqual(0.6);
    expect(r.drivers.length).toBeGreaterThan(0);
  });
});
