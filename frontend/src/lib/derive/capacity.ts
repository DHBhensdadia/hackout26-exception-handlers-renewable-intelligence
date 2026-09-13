import type { ForecastResponse, SiteRecord } from "@/types";
import { demandForSite } from "./balance";
import { hash01, round } from "./util";

export interface CapacityYear {
  year: number;
  demand: number;
  capacity: number;
  gap: number;
}

export interface CapacityResult {
  years: CapacityYear[];
  growthPct: number;
  capacityGapMw: number;
  requiredStorageMwh: number;
  note: string;
}

/**
 * Module 6 — future demand & capacity planning (spec §12).
 * Population/industrial growth is modelled as a deterministic compounding rate.
 */
export function capacityModel(forecast: ForecastResponse, site: SiteRecord): CapacityResult {
  const growth = 0.045 + hash01(site.site_id + ":growth") * 0.02; // 4.5–6.5 %/yr
  const demand = demandForSite(site, forecast.points);
  const base = Math.max(...demand, 1);
  const startYear = new Date(forecast.issue_time_utc).getUTCFullYear();

  const years: CapacityYear[] = Array.from({ length: 5 }, (_, k) => {
    const d = round(base * (1 + growth) ** k, 1);
    return { year: startYear + k, demand: d, capacity: site.capacity_mw, gap: round(d - site.capacity_mw, 1) };
  });

  const capacityGapMw = Math.max(0, years[years.length - 1].gap);
  const surplusP90 = forecast.points.reduce((a, p, i) => a + Math.max(0, p.p90_mw - demand[i]), 0);
  const requiredStorageMwh = Math.round((surplusP90 / Math.max(1, forecast.points.length)) * 24 * 2);

  const covered = round((site.capacity_mw / years[0].demand) * 100, 0);
  return {
    years,
    growthPct: round(growth * 100, 1),
    capacityGapMw,
    requiredStorageMwh,
    note: `${site.capacity_mw} MW covers ${covered} % of today's peak; demand compounds at ${(growth * 100).toFixed(1)} %/yr.`,
  };
}
