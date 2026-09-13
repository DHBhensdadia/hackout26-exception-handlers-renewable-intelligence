import type { SiteRecord } from "@/types";
import { clamp, hash01, round } from "./util";

export type ScenarioKey = "A" | "B" | "C" | "D" | "E";

export interface Allocation {
  tech: "Solar" | "Wind" | "Storage";
  cr: number;
  pct: number;
}

export interface Scenario {
  key: ScenarioKey;
  name: string;
  capex_cr: number;
  solar_mw: number;
  wind_mw: number;
  storage_mwh: number;
  annual_gen_gwh: number;
  demand_met_pct: number;
  roi_pct: number;
  payback_yr: number;
  risk: { label: string; tone: "ok" | "warn" | "bad" };
  allocation: Allocation[];
  recommended: boolean;
}

const SOLAR_CR_MW = 4.5;
const WIND_CR_MW = 6;
const STORAGE_CR_MWH = 1.6;
const CUF_SOLAR = 0.19;
const CUF_WIND = 0.3;
const OM_PCT = 0.015;
/** GWh × ₹3/kWh = GWh × 0.3 crore */
const REVENUE_CR_PER_GWH = 0.3;

const MIX: Record<ScenarioKey, { name: string; solar: number; wind: number; storage: number }> = {
  A: { name: "100 % Solar", solar: 1, wind: 0, storage: 0 },
  B: { name: "Solar + Storage", solar: 0.78, wind: 0, storage: 0.22 },
  C: { name: "Wind + Storage", solar: 0, wind: 0.78, storage: 0.22 },
  D: { name: "Solar + Wind", solar: 0.55, wind: 0.45, storage: 0 },
  E: { name: "Hybrid + Storage", solar: 0.4, wind: 0.36, storage: 0.24 },
};

/**
 * Modules 5 & 7 — investment scenarios against a budget (spec §11, §13, §27).
 * Presented as a scenario comparison, never as a guaranteed financial forecast.
 * `baselineDemandMet` anchors the scenarios to the site's measured balance so
 * §07 does not contradict §01.
 */
export function investmentScenarios(budgetCr: number, site: SiteRecord, baselineDemandMet = 68): Scenario[] {
  const base = clamp(baselineDemandMet, 28, 92);
  const h = hash01(site.site_id + ":invest") - 0.5;

  const scenarios = (Object.keys(MIX) as ScenarioKey[]).map((key) => {
    const m = MIX[key];
    const solarCr = budgetCr * m.solar;
    const windCr = budgetCr * m.wind;
    const storageCr = budgetCr * m.storage;

    const solar_mw = round(solarCr / SOLAR_CR_MW, 1);
    const wind_mw = round(windCr / WIND_CR_MW, 1);
    const storage_mwh = Math.round(storageCr / STORAGE_CR_MWH);

    const annualGenGwh = round((solar_mw * 8760 * CUF_SOLAR + wind_mw * 8760 * CUF_WIND) / 1000, 1);
    const revenueCr = annualGenGwh * REVENUE_CR_PER_GWH;
    const omCr = budgetCr * OM_PCT;
    const netCr = Math.max(0.1, revenueCr - omCr);

    const roi = clamp(round((netCr / budgetCr) * 100, 1), 1, 30);
    const payback = clamp(round(budgetCr / netCr, 1), 3, 40);

    const diversity = (m.solar > 0 ? 1 : 0) + (m.wind > 0 ? 1 : 0);
    const demandMet = clamp(Math.round(base + m.storage * 80 + (diversity - 1) * 5 + h * 4), 28, 96);
    const riskScore = clamp(0.62 - m.storage * 0.9 - (diversity - 1) * 0.14 + h * 0.06, 0.08, 0.7);
    const risk: Scenario["risk"] =
      riskScore < 0.3
        ? { label: "Lower", tone: "ok" }
        : riskScore < 0.5
          ? { label: "Moderate", tone: "warn" }
          : { label: "Higher", tone: "bad" };

    const allocation: Allocation[] = [
      ...(m.solar > 0 ? [{ tech: "Solar" as const, cr: Math.round(solarCr), pct: Math.round(m.solar * 100) }] : []),
      ...(m.wind > 0 ? [{ tech: "Wind" as const, cr: Math.round(windCr), pct: Math.round(m.wind * 100) }] : []),
      ...(m.storage > 0 ? [{ tech: "Storage" as const, cr: Math.round(storageCr), pct: Math.round(m.storage * 100) }] : []),
    ];

    const score = (demandMet / 100) * 0.4 + (roi / 30) * 0.4 + (1 - riskScore) * 0.2;

    return {
      key,
      name: m.name,
      capex_cr: budgetCr,
      solar_mw,
      wind_mw,
      storage_mwh,
      annual_gen_gwh: annualGenGwh,
      demand_met_pct: demandMet,
      roi_pct: roi,
      payback_yr: payback,
      risk,
      allocation,
      recommended: false,
      _score: score,
    };
  });

  const best = scenarios.reduce((a, b) => (b._score > a._score ? b : a), scenarios[0]);
  return scenarios.map(({ _score, ...s }) => ({ ...s, recommended: s.key === best.key }));
}
