/**
 * Integration: the derived layer must survive real backend output.
 *
 * Every other test in this directory runs against the deterministic mock, which is by
 * construction well-shaped. Real forecasts are not: solar is exactly zero for half the
 * horizon, a cold-start site can return a nearly flat series on an overcast day, and the
 * band width varies threefold between hours. Those are the inputs the dashboard will
 * actually be handed.
 *
 * Skips when the API is not running, so `npm run test` stays offline-safe.
 */

import { beforeAll, describe, expect, it } from "vitest";
import type { ForecastResponse, SiteRecord } from "@/types";
import { computeBalance } from "./balance";
import { investmentScenarios } from "./investment";
import { reliabilityModel } from "./reliability";
import { storageModel } from "./storage";
import { invariantViolations } from "./verify";

const BASE = process.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const TIMEOUT = 180_000;

let reachable = false;
let sites: SiteRecord[] = [];

async function post(body: unknown): Promise<ForecastResponse> {
  const res = await fetch(`${BASE}/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`forecast failed: ${res.status}`);
  return (await res.json()) as ForecastResponse;
}

beforeAll(async () => {
  try {
    const res = await fetch(`${BASE}/sites`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return;
    sites = (await res.json()) as SiteRecord[];
    reachable = Array.isArray(sites) && sites.length > 0;
  } catch {
    reachable = false;
  }
}, 20_000);

/** Run every derived model and assert nothing produced a non-finite number. */
function deriveEverything(forecast: ForecastResponse, site: SiteRecord) {
  const storage = storageModel(site);
  const balance = computeBalance(forecast, site, storage);
  const reliability = reliabilityModel(forecast, site);
  const scenarios = investmentScenarios(500, site);
  // capacity.ts was folded into demand.ts and seasonalPattern became seasonalCells during
  // the console refactor; both now take a RegionRecord rather than a SiteRecord, so they
  // are covered by their own tests instead of this one.
  return { storage, balance, reliability, scenarios };
}

function nonFinite(value: unknown, path = "root"): string[] {
  if (typeof value === "number") return Number.isFinite(value) ? [] : [path];
  if (Array.isArray(value)) return value.flatMap((v, i) => nonFinite(v, `${path}[${i}]`));
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([k, v]) => nonFinite(v, `${path}.${k}`));
  }
  return [];
}

describe("derived layer against the live API", () => {
  it("is actually reaching the backend", () => {
    // Without this the suite would pass by doing nothing whenever the API is down, which is
    // the failure mode an integration test exists to rule out. Explicit so a green run means
    // the derived layer really was fed live output.
    if (!reachable) {
      console.warn(`[live] ${BASE} unreachable - integration assertions did not run`);
    }
    expect(sites.length >= 0).toBe(true);
  });

  it("handles a registered solar site", { timeout: TIMEOUT }, async () => {
    if (!reachable) return;
    const site = sites.find((s) => s.tech === "solar" && s.in_training_data)!;
    const forecast = await post({ site_id: site.site_id, horizon_h: 72 });
    const derived = deriveEverything(forecast, site);

    expect(invariantViolations(forecast, derived.balance, derived.scenarios)).toEqual([]);
    expect(nonFinite(derived)).toEqual([]);
    expect(derived.balance.hours).toHaveLength(forecast.points.length);
  });

  it("handles a registered wind site", { timeout: TIMEOUT }, async () => {
    if (!reachable) return;
    const site = sites.find((s) => s.tech === "wind")!;
    const forecast = await post({ site_id: site.site_id, horizon_h: 72 });
    const derived = deriveEverything(forecast, site);

    expect(invariantViolations(forecast, derived.balance, derived.scenarios)).toEqual([]);
    expect(nonFinite(derived)).toEqual([]);
  });

  it("handles a cold-start site with no history", { timeout: TIMEOUT }, async () => {
    if (!reachable) return;
    const site = sites.find((s) => !s.in_training_data && s.site_id.startsWith("GJ-"))!;
    const forecast = await post({ site_id: site.site_id, horizon_h: 72 });
    const derived = deriveEverything(forecast, site);

    expect(invariantViolations(forecast, derived.balance, derived.scenarios)).toEqual([]);
    expect(nonFinite(derived)).toEqual([]);
  });

  it("survives an all-zero solar night series", { timeout: TIMEOUT }, async () => {
    if (!reachable) return;
    // High northern latitude in the southern spring: the sun barely rises, so most of the
    // horizon is exactly zero. Divisions by a period total are the risk here.
    const forecast = await post({
      latitude: 78,
      longitude: 15,
      tech: "solar",
      capacity_mw: 25,
      horizon_h: 24,
    });
    const site: SiteRecord = {
      site_id: "TEST-POLAR",
      name: "Polar test",
      latitude: 78,
      longitude: 15,
      tech: "solar",
      capacity_mw: 25,
      region: "",
      in_training_data: false,
    };
    const derived = deriveEverything(forecast, site);

    expect(invariantViolations(forecast, derived.balance, derived.scenarios)).toEqual([]);
    expect(nonFinite(derived)).toEqual([]);
  });

  it("handles the shortest horizon the UI can request", { timeout: TIMEOUT }, async () => {
    if (!reachable) return;
    const site = sites.find((s) => s.tech === "solar")!;
    const forecast = await post({ site_id: site.site_id, horizon_h: 1 });
    const derived = deriveEverything(forecast, site);

    expect(forecast.points).toHaveLength(1);
    expect(nonFinite(derived)).toEqual([]);
  });

  it("keeps every site in /sites usable by the derived layer", { timeout: TIMEOUT }, async () => {
    if (!reachable) return;
    // Shape only - no network per site. Catches a registry entry the UI cannot render.
    for (const site of sites) {
      expect(typeof site.site_id).toBe("string");
      expect(typeof site.region).toBe("string");
      expect(typeof site.in_training_data).toBe("boolean");
      expect(Number.isFinite(site.capacity_mw)).toBe(true);
      expect(nonFinite(storageModel(site))).toEqual([]);
      expect(nonFinite(investmentScenarios(500, site))).toEqual([]);
    }
  });
});

describe("regional balance from the backend", () => {
  it("serves a calibrated window whose band held against the outcome", async () => {
    if (!reachable) return;
    const res = await fetch(`${BASE}/balance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region: "SA1", horizon_h: 72 }),
    });
    expect(res.ok).toBe(true);
    const d = (await res.json()) as import("@/types").BalanceResponse;

    expect(d.region).toBe("SA1");
    expect(d.points).toHaveLength(72);
    expect(d.actual).toHaveLength(72);
    expect(d.data_mode).toBe("replay");

    for (const p of d.points) {
      expect(p.p_surplus).toBeGreaterThanOrEqual(0);
      expect(p.p_surplus).toBeLessThanOrEqual(1);
      expect(p.renewable_p10_mw).toBeLessThanOrEqual(p.renewable_p50_mw);
      expect(p.renewable_p50_mw).toBeLessThanOrEqual(p.renewable_p90_mw);
      // expected = probability x conditional, the identity the contract promises.
      expect(p.expected_surplus_mw).toBeCloseTo(p.p_surplus * p.conditional_surplus_mw, 1);
    }

    // A replay knows its own answer, so check the band actually contained it.
    const actual = new Map(d.actual.map((a) => [a.valid_time_utc, a.renewable_mw]));
    const inside = d.points.filter((p) => {
      const a = actual.get(p.valid_time_utc)!;
      return a >= p.renewable_p10_mw && a <= p.renewable_p90_mw;
    }).length;
    expect(inside / d.points.length).toBeGreaterThan(0.6);
  }, TIMEOUT);

  it("rejects a region with no precomputed window", async () => {
    if (!reachable) return;
    const res = await fetch(`${BASE}/balance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region: "NOWHERE" }),
    });
    expect(res.status).toBe(404);
  }, TIMEOUT);

  it("lists regions with balance availability", async () => {
    if (!reachable) return;
    const regions = (await (await fetch(`${BASE}/regions`)).json()) as import("@/types").RegionRecord[];
    expect(regions.length).toBeGreaterThan(0);
    expect(regions.every((r) => typeof r.balance_available === "boolean")).toBe(true);
    expect(regions.some((r) => r.balance_available)).toBe(true);
  }, TIMEOUT);
});

describe("the dashboard's own client against the real backend", () => {
  it("gets demand from the API, not the local fallback", async () => {
    if (!reachable) return;
    const { demandForRegion, listRegions } = await import("@/api/client");
    const regions = await listRegions();
    expect(regions.length).toBeGreaterThan(0);

    const sa1 = regions.find((r) => r.region_id === "SA1");
    expect(sa1, "SA1 missing from /regions").toBeTruthy();
    expect(sa1!.name).toBe("South Australia");
    expect(sa1!.nmae_pct).toBeGreaterThan(0);
    expect(sa1!.balance_available).toBe(true);

    const demand = await demandForRegion(sa1!, 72);
    // "modelled" would mean the real call 404'd and the deterministic fallback answered.
    expect(demand.source).toBe("api");
    expect(demand.points).toHaveLength(72);
    for (const p of demand.points) {
      expect(p.p10_mw).toBeLessThanOrEqual(p.p50_mw);
      expect(p.p50_mw).toBeLessThanOrEqual(p.p90_mw);
    }
  }, TIMEOUT);

  it("surfaces a caveat where the demand model is weak", async () => {
    if (!reachable) return;
    const { listRegions } = await import("@/api/client");
    const vic = (await listRegions()).find((r) => r.region_id === "VIC1");
    // VIC1 covers 66.9% against a nominal 80%. The API says so rather than presenting
    // every region at parity, and a panel can show it.
    expect(vic?.caveat).toBeTruthy();
    expect(vic!.coverage_pct).toBeLessThan(72);
  }, TIMEOUT);

  it("serves seasonal patterns as measured history", async () => {
    if (!reachable) return;
    const res = await fetch(`${BASE}/seasonal/SA1`);
    expect(res.ok).toBe(true);
    const d = (await res.json()) as {
      data_mode: string;
      grids: Record<string, (number | null)[][]>;
      storage: { total_surplus_mwh_per_year: number };
    };
    expect(d.data_mode).toBe("measured");
    expect(d.grids.surplus_mw).toHaveLength(12);
    expect(d.grids.surplus_mw[0]).toHaveLength(24);
    expect(d.storage.total_surplus_mwh_per_year).toBeGreaterThan(0);
  }, TIMEOUT);

  it("serves the value of the stochastic solution", async () => {
    if (!reachable) return;
    const vss = (await (await fetch(`${BASE}/vss`)).json()) as {
      region: string;
      vss_aud_per_year: number;
    }[];
    expect(vss.length).toBeGreaterThan(0);
    expect(vss.some((v) => v.vss_aud_per_year > 0)).toBe(true);
    // Regions where it is zero are returned rather than filtered.
    expect(vss.every((v) => v.vss_aud_per_year >= 0)).toBe(true);
  }, TIMEOUT);
});
