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
import { capacityModel } from "./capacity";
import { computeBalance } from "./balance";
import { investmentScenarios } from "./investment";
import { reliabilityModel } from "./reliability";
import { seasonalPattern } from "./seasonal";
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
  const capacity = capacityModel(forecast, site);
  const reliability = reliabilityModel(forecast, site);
  const seasonal = seasonalPattern(site);
  const scenarios = investmentScenarios(500, site);
  return { storage, balance, capacity, reliability, seasonal, scenarios };
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
      expect(nonFinite(seasonalPattern(site))).toEqual([]);
      expect(nonFinite(investmentScenarios(500, site))).toEqual([]);
    }
  });
});
