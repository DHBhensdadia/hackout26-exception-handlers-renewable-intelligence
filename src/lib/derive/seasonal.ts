import type { SiteRecord } from "@/types";
import { hash01, round } from "./util";

export interface SeasonalMonth {
  month: string;
  gen: number;
  demand: number;
  pattern: "surplus" | "balanced" | "shortage";
}

export interface SeasonalNote {
  title: string;
  body: string;
}

export interface SeasonalResult {
  months: SeasonalMonth[];
  notes: SeasonalNote[];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Seasonal generation shapes for the Indian grid (relative to installed potential). */
const SOLAR_SHAPE = [0.72, 0.78, 0.92, 0.98, 1.0, 0.86, 0.6, 0.58, 0.68, 0.85, 0.8, 0.7];
const WIND_SHAPE = [0.85, 0.8, 0.75, 0.78, 0.9, 1.0, 1.05, 1.0, 0.9, 0.78, 0.8, 0.88];
const DEMAND_SHAPE = [0.85, 0.88, 0.95, 1.0, 1.05, 1.0, 0.95, 0.92, 0.9, 0.88, 0.85, 0.86];

/**
 * Module 3 — seasonal pattern analysis (spec §9).
 * Turns the forecast horizon into the recurring pattern that outlives it.
 */
export function seasonalPattern(site: SiteRecord): SeasonalResult {
  const genScale = 0.82 + hash01(site.site_id + ":season") * 0.18;
  const shape = site.tech === "solar" ? SOLAR_SHAPE : WIND_SHAPE;

  const months: SeasonalMonth[] = MONTHS.map((month, i) => {
    const gen = round(shape[i] * genScale * 100, 0);
    const demand = round(DEMAND_SHAPE[i] * 100, 0);
    const pattern: SeasonalMonth["pattern"] =
      gen > demand * 1.08 ? "surplus" : gen < demand * 0.92 ? "shortage" : "balanced";
    return { month, gen, demand, pattern };
  });

  const byGen = [...months].sort((a, b) => b.gen - a.gen);
  const byDemand = [...months].sort((a, b) => b.demand - a.demand);
  const surplus = months.filter((m) => m.pattern === "surplus").map((m) => m.month);
  const shortage = months.filter((m) => m.pattern === "shortage").map((m) => m.month);

  const notes: SeasonalNote[] = [
    {
      title: "Peak generation",
      body: `${byGen[0].month} runs at ${byGen[0].gen} % of installed potential — the strongest surplus window of the year.`,
    },
    {
      title: surplus.length >= 3 ? "Recurring surplus" : "Surplus windows",
      body: surplus.length
        ? `${surplus.slice(0, 3).join(", ")}${surplus.length > 3 ? "…" : ""} consistently exceed demand — storage sized here pays back fastest.`
        : "No month exceeds demand by more than 8 % — generation is well matched to load.",
    },
    {
      title: "High-demand season",
      body: `${byDemand[0].month} carries the year's peak demand — the month to hold backup headroom.`,
    },
  ];

  if (site.tech === "solar" && shortage.length) {
    notes.push({
      title: "Monsoon dip",
      body: `${shortage[0]}–${shortage[shortage.length - 1]} is the low-output window for solar; plan maintenance and backup here.`,
    });
  }

  return { months, notes: notes.slice(0, 3) };
}
