import { hash01 } from "@/lib/derive/util";
import { demandBand, summarizeDemand, type DemandResult } from "@/lib/derive";
import type {
  ColdStartForecastRequest,
  ForecastRequest,
  ForecastResponse,
  HourPoint,
  RegionRecord,
  SiteForecastRequest,
  SiteRecord,
  Tech,
} from "../types";

/* =============================================================
   Deterministic mock data generator.
   Produces responses that obey the EXACT /forecast contract in
   input_output.md (xgb-q-0.1.0, 6 models = 2 tech x 3 quantiles):
     - always p10 <= p50 <= p90
     - all MW values in [0, capacity_mw]
     - solar exactly 0 at night
     - envelope fields present
   A per-run seed makes a fresh-looking but stable run each time.
   ============================================================= */

function mulberry32(a: number) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Fixed list of registered sites (stands in for GET /sites). */
const MOCK_SITES: SiteRecord[] = [
  { site_id: "GJ-SOLAR-CHARANKA", name: "Charanka Solar Park", latitude: 23.03, longitude: 72.57, tech: "solar", capacity_mw: 50, region: "Gujarat", in_training_data: true },
  { site_id: "RJ-SOLAR-BHADLA", name: "Bhadla Solar Park", latitude: 27.5, longitude: 71.92, tech: "solar", capacity_mw: 120, region: "Rajasthan", in_training_data: true },
  { site_id: "TN-WIND-KAYATHAR", name: "Kayathar Wind Farm", latitude: 8.7, longitude: 77.7, tech: "wind", capacity_mw: 73, region: "Tamil Nadu", in_training_data: true },
  { site_id: "GJ-WIND-JAMSHED", name: "Jamnagar Wind Cluster", latitude: 22.47, longitude: 70.06, tech: "wind", capacity_mw: 45, region: "Gujarat", in_training_data: true },
  { site_id: "MH-SOLAR-SATARA", name: "Satara Solar Ridge", latitude: 17.5, longitude: 74.02, tech: "solar", capacity_mw: 32, region: "Maharashtra", in_training_data: false },
  { site_id: "AP-WIND-ANANTA", name: "Anantapur Wind Ridge", latitude: 14.68, longitude: 77.6, tech: "wind", capacity_mw: 38, region: "Andhra Pradesh", in_training_data: false },
  { site_id: "GJ-HYBRID-KUTCH", name: "Kutch Hybrid (Solar + Wind)", latitude: 23.7, longitude: 69.9, tech: "solar", capacity_mw: 90, region: "Gujarat", in_training_data: true },
  { site_id: "KA-SOLAR-PAVAGADA", name: "Pavagada Solar Park", latitude: 14.17, longitude: 77.27, tech: "solar", capacity_mw: 85, region: "Karnataka", in_training_data: true },
];

function pick<T>(arr: T[], rng: () => number): T {
  return arr[Math.floor(rng() * arr.length)];
}

/**
 * Regional demand model metadata (GET /regions). nMAE and coverage are the
 * measured figures from model-outputs-and-visualisation.md §2.2; VIC1 is the
 * documented seasonal-bias limitation and must not be shown at parity.
 * `balance_available` mirrors where POST /balance is served.
 */
const MOCK_REGIONS: RegionRecord[] = [
  { region_id: "QLD1", name: "Queensland", nmae_pct: 1.84, coverage_pct: 80.2, balance_available: false, headroom_mw: 6500 },
  { region_id: "NSW1", name: "New South Wales", nmae_pct: 2.27, coverage_pct: 82.6, balance_available: true, headroom_mw: 10000 },
  { region_id: "SA1", name: "South Australia", nmae_pct: 3.17, coverage_pct: 84.6, balance_available: true, headroom_mw: 1610 },
  { region_id: "TAS1", name: "Tasmania", nmae_pct: 4.15, coverage_pct: 88.8, balance_available: false, headroom_mw: 1000 },
  {
    region_id: "VIC1",
    name: "Victoria",
    nmae_pct: 4.33,
    coverage_pct: 66.9,
    balance_available: false,
    headroom_mw: 4200,
    caveat: "Seasonal bias no scalar correction reaches — do not present at parity.",
  },
];

interface SolarProfile {
  kind: "solar";
  clearSkyFactor: number;
  hour12: number;
  morning: number;
}
interface WindProfile {
  kind: "wind";
  wind: number;
}

function solarProfile(rng: () => number): SolarProfile {
  const clearSkyFactor = 0.78 + rng() * 0.18;
  const world = pick([0.34, 0.4, 0.46, 0.3], rng);
  const hour12 = Math.floor(world * 24);
  const morning = 0.82 + rng() * 0.3;
  return { kind: "solar", clearSkyFactor, hour12, morning };
}

function windProfile(rng: () => number): WindProfile {
  const wind = 6 + rng() * 4;
  return { kind: "wind", wind };
}

type SiteIdSpec = { site_id?: string; latitude?: number; longitude?: number };

/** The core run: generate a forecast for a request. */
function runForecast(
  req: ForecastRequest & { capacity_mw: number; tech: Tech },
  rng: () => number
): { points: HourPoint[]; envelope: Pick<ForecastResponse, "site_id" | "tech" | "issue_time_utc" | "location_is_estimated" | "capacity_mw"> } {
  const { capacity_mw, tech, horizon_h = 72 } = req;
  const H = Math.max(1, Math.min(72, horizon_h));
  const hourly = tech === "solar" ? solarProfile(rng) : windProfile(rng);

  const issueTime = new Date();
  issueTime.setUTCMinutes(0, 0, 0);

  const points: HourPoint[] = [];
  for (let i = 0; i < H; i++) {
    const t = new Date(issueTime.getTime() + i * 3600_000);
    const hourOfDay = t.getUTCHours();
    const lead = i + 1;

    let clearsky: number;
    let physics: number;
    let p50: number;
    let p10: number;
    let p90: number;

    if (tech === "solar" && hourly.kind === "solar") {
      const diff = Math.abs(hourOfDay - hourly.hour12);
      const dayFrac = diff > 12 ? 24 - diff : diff;
      if (dayFrac >= 11.5) {
        clearsky = 0;
        physics = 0;
        p50 = 0;
        p10 = 0;
        p90 = 0;
      } else {
        const elev = Math.cos((dayFrac / 12) * Math.PI);
        const clear = Math.max(0, capacity_mw * hourly.clearSkyFactor * elev);
        clearsky = Math.round(clear * 100) / 100;

        const physFrac = 0.62 + rng() * hourly.morning * 0.25;
        physics = Math.min(capacity_mw, clearsky * physFrac);

        const cov = 0.3 + rng() * 0.4;
        const p50f = clearsky * (1 - cov * 0.5);
        const width = clearsky * (0.08 + rng() * 0.16);
        p50 = Math.min(capacity_mw, Math.max(0, p50f));
        p10 = Math.max(0, p50 - width);
        p90 = Math.min(capacity_mw, p50 + width);
      }
    } else {
      const wind = hourly.kind === "wind" ? hourly.wind : 8;
      const eff = wind * (0.7 + rng() * 0.5);
      const capFrac = eff / (wind + 3.5);
      const cf = Math.max(0.02, Math.min(0.62, capFrac));
      const clear = capacity_mw * cf;

      clearsky = Math.round(clear * 100) / 100;
      const physFrac = 0.8 + rng() * 0.3;
      physics = Math.min(capacity_mw, clearsky * physFrac);

      const p50f = clearsky * (0.75 + rng() * 0.2);
      const width = capacity_mw * (0.06 + rng() * 0.12);
      p50 = Math.min(capacity_mw, Math.max(0, p50f));
      p10 = Math.max(0, p50 - width);
      p90 = Math.min(capacity_mw, p50 + width);
    }

    // Guarantee ordering + clamp (contract: always p10 <= p50 <= p90).
    const vals = [p10, p50, p90].sort((a, b) => a - b);
    const [lo, mid, hi] = vals;
    points.push({
      valid_time_utc: t.toISOString(),
      horizon_h: lead,
      p10_mw: Math.round(Math.min(capacity_mw, Math.max(0, lo)) * 100) / 100,
      p50_mw: Math.round(Math.min(capacity_mw, Math.max(0, mid)) * 100) / 100,
      p90_mw: Math.round(Math.min(capacity_mw, Math.max(0, hi)) * 100) / 100,
      clearsky_mw: Math.round(clearsky * 100) / 100,
      physics_mw: Math.round(physics * 100) / 100,
    });
  }

  const spec = req as ForecastRequest & SiteIdSpec;
  const isSite = "site_id" in req && !!spec.site_id;
  const site_id = isSite ? spec.site_id! : `adhoc-${spec.latitude ?? 0},${spec.longitude ?? 0}`;

  return {
    points,
    envelope: {
      site_id,
      tech,
      issue_time_utc: issueTime.toISOString(),
      location_is_estimated: !isSite,
      capacity_mw,
    },
  };
}

/** Simulate a little network latency and honour the caller's abort signal. */
function simulateLatency(signal?: AbortSignal, ms = 220): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Stable seed so the same request always yields the same shape. */
function seedFor(req: unknown): number {
  return Math.floor(hash01(JSON.stringify(req)) * 0xffffffff) >>> 0;
}

/** Public mock API surface. */
export const mockApi = {
  async listSites(signal?: AbortSignal): Promise<SiteRecord[]> {
    await simulateLatency(signal, 120);
    return MOCK_SITES.map((s) => ({ ...s }));
  },

  async listRegions(signal?: AbortSignal): Promise<RegionRecord[]> {
    await simulateLatency(signal, 120);
    return MOCK_REGIONS.map((r) => ({ ...r }));
  },

  /** POST /demand stand-in — the regional band plus its planning read. */
  async demand(region: RegionRecord, horizonH: number, signal?: AbortSignal): Promise<DemandResult> {
    await simulateLatency(signal, 160);
    const issue = new Date();
    issue.setUTCMinutes(0, 0, 0);
    return summarizeDemand(demandBand(region, issue, horizonH), region, issue.getUTCFullYear());
  },

  async forecast(
    req: ForecastRequest & { capacity_mw: number; tech: Tech },
    signal?: AbortSignal
  ): Promise<ForecastResponse> {
    await simulateLatency(signal);
    const rng = mulberry32(seedFor(req));
    const { points, envelope } = runForecast(req, rng);

    return {
      ...envelope,
      model_version: "xgb-q-0.1.0",
      weather_source: "openmeteo:icon_seamless",
      points,
    };
  },
};

export type { SiteForecastRequest, ColdStartForecastRequest };