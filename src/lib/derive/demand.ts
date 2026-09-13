import type { DemandPoint, DemandResponse, RegionRecord } from "@/types";
import { REGION_PROFILES, demandAt, renewableAt } from "./history";
import { hash01, round } from "./util";

export interface RegionPlanYear {
  year: number;
  demand: number;
  renewable: number;
  gap: number;
}

export interface RegionPlan {
  years: RegionPlanYear[];
  growthPct: number;
  note: string;
}

/** The demand model's output plus the planning read that follows from it. */
export interface DemandResult extends DemandResponse {
  peak: DemandPoint;
  mean_mw: number;
  headroom_mw: number;
  /** Dispatchable headroom minus the peak — negative means demand outruns it. */
  peak_margin_mw: number;
  /** Installed renewable capacity assumed for the region (modelled). */
  renewable_mw: number;
  /** Regional renewable band on the same axis, for the mirrored-band reading. */
  renewable_band: DemandPoint[];
  plan: RegionPlan;
}

/** 80 % interval half-width for a calibrated quantile model. */
const WIDTH_PER_NMAE = 1.6;

/** Regional demand band for the next `horizonH` hours (POST /demand stand-in). */
export function demandBand(region: RegionRecord, issueTime: Date, horizonH: number): DemandResponse {
  const profile = REGION_PROFILES[region.region_id];
  const H = Math.max(1, Math.min(72, horizonH));
  const halfWidth = (region.nmae_pct / 100) * WIDTH_PER_NMAE;

  const points: DemandPoint[] = [];
  for (let i = 0; i < H; i++) {
    const t = new Date(issueTime.getTime() + i * 3_600_000);
    const p50 = demandAt(profile, t);
    const w = p50 * halfWidth;
    const p10 = Math.max(0, p50 - w);
    const p90 = p50 + w;
    points.push({
      valid_time_utc: t.toISOString(),
      horizon_h: i + 1,
      p10_mw: round(p10, 1),
      p50_mw: round(p50, 1),
      p90_mw: round(p90, 1),
    });
  }

  return {
    region_id: region.region_id,
    data_mode: "replay",
    model_version: "demand-q-0.1.0",
    nmae_pct: region.nmae_pct,
    coverage_pct: region.coverage_pct,
    points,
    source: "modelled",
  };
}

/** Long-run planning read: compounding demand against fixed renewable capacity. */
export function regionPlan(region: RegionRecord, peakMw: number, startYear: number): RegionPlan {
  const profile = REGION_PROFILES[region.region_id];
  const growth = 0.032 + hash01(`${region.region_id}:growth`) * 0.023; // 3.2–5.5 %/yr
  const renewable = profile.solar_capacity_mw + profile.wind_capacity_mw;

  const years: RegionPlanYear[] = Array.from({ length: 5 }, (_, k) => {
    const demand = round(peakMw * (1 + growth) ** k, 0);
    return { year: startYear + k, demand, renewable, gap: round(demand - renewable, 0) };
  });

  const gap = years[years.length - 1].gap;
  return {
    years,
    growthPct: round(growth * 100, 1),
    note:
      gap > 0
        ? `Demand compounds at ${(growth * 100).toFixed(1)} %/yr and passes today's ${renewable} MW of regional renewables by ${years.find((y) => y.gap > 0)?.year}.`
        : `${renewable} MW of regional renewables covers the ${years[years.length - 1].demand} MW ${years[years.length - 1].year} peak; the ${Math.abs(gap)} MW margin is the headroom to defend.`,
  };
}

/** Wrap a demand response with the figures the panel leads with. */
export function summarizeDemand(resp: DemandResponse, region: RegionRecord, startYear: number): DemandResult {
  const points = resp.points;
  const profile = REGION_PROFILES[region.region_id];
  const peak = points.reduce((a, p) => (p.p50_mw > a.p50_mw ? p : a), points[0]);
  const mean = points.reduce((a, p) => a + p.p50_mw, 0) / Math.max(1, points.length);
  const renewable_band: DemandPoint[] = points.map((p) => {
    const mid = renewableAt(profile, new Date(p.valid_time_utc));
    const w = mid * 0.06;
    return {
      valid_time_utc: p.valid_time_utc,
      horizon_h: p.horizon_h,
      p10_mw: round(Math.max(0, mid - w), 1),
      p50_mw: round(mid, 1),
      p90_mw: round(mid + w, 1),
    };
  });

  return {
    ...resp,
    peak,
    mean_mw: round(mean, 0),
    headroom_mw: region.headroom_mw,
    peak_margin_mw: round(region.headroom_mw - peak.p50_mw, 0),
    renewable_mw: profile.solar_capacity_mw + profile.wind_capacity_mw,
    renewable_band,
    plan: regionPlan(region, peak.p50_mw, startYear),
  };
}
