import type { RegionRecord, SeasonalCell, SeasonalResponse } from "@/types";
import { REGION_PROFILES, forEachHistoryStep } from "./history";
import { round } from "./util";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;

export interface SeasonalMonthSummary {
  month: string;
  /** Mean median residual across the month, MW (negative = surplus). */
  residual: number;
  /** Expected surplus hours in this month, per year. */
  surplus_hours: number;
  /** Expected surplus energy in this month, MWh per year. */
  surplus_mwh: number;
}

export interface SeasonalResult extends SeasonalResponse {
  months: SeasonalMonthSummary[];
  peak: { month: number; hour: number; residual_mwh: number };
  recurring_surplus_hours: number;
  recurring_surplus_mwh: number;
  headline: string;
}

/**
 * Storage sized to shift a typical day's recurring surplus into its recurring
 * deficit, in the month that needs the most. Bounded by the deficit so storage
 * is only built for energy the region can actually use.
 */
function storageToAbsorb(cells: SeasonalCell[]): number {
  let best = 0;
  for (let m = 0; m < 12; m++) {
    const day = cells.filter((c) => c.month === m).sort((a, b) => a.hour - b.hour);
    const surplus = day.reduce((a, c) => a + Math.max(0, c.residual_mwh), 0);
    const deficit = day.reduce((a, c) => a + Math.max(0, -c.residual_mwh), 0);
    best = Math.max(best, deficit > 0 ? Math.min(surplus, deficit) : surplus);
  }
  return Math.round(best);
}

/** Month x hour grid computed from three years of the regional climatology. */
export function seasonalCells(region: RegionRecord): SeasonalResponse {
  const profile = REGION_PROFILES[region.region_id];
  const buckets: number[][][] = Array.from({ length: 12 }, () =>
    Array.from({ length: 24 }, () => [] as number[])
  );

  forEachHistoryStep(profile, ({ month, hour, residual_mwh }) => {
    buckets[month][hour].push(residual_mwh);
  });

  const cells: SeasonalCell[] = [];
  for (let m = 0; m < 12; m++) {
    for (let h = 0; h < 24; h++) {
      const arr = buckets[m][h].sort((a, b) => a - b);
      const median = arr[Math.floor(arr.length / 2)] ?? 0;
      const surplus = arr.filter((v) => v > 0).length / Math.max(1, arr.length);
      cells.push({ month: m, hour: h, residual_mwh: round(median, 0), surplus_pct: round(surplus, 2) });
    }
  }

  return {
    region_id: region.region_id,
    window_years: 3,
    source: "AEMO 2022–2024 climatology",
    cells,
    storage_to_absorb_mwh: storageToAbsorb(cells),
  };
}

/** The reads the module leads with. */
export function summarizeSeasonal(resp: SeasonalResponse): SeasonalResult {
  const cells = resp.cells;
  const months: SeasonalMonthSummary[] = MONTHS.map((month, m) => {
    const day = cells.filter((c) => c.month === m);
    let surplus_hours = 0;
    let surplus_mwh = 0;
    let total = 0;
    for (const c of day) {
      total += c.residual_mwh;
      if (c.residual_mwh > 0) {
        surplus_hours += DAYS[m];
        surplus_mwh += c.residual_mwh * DAYS[m];
      }
    }
    return { month, residual: round(total / 24, 0), surplus_hours, surplus_mwh: round(surplus_mwh, 0) };
  });

  const peak = cells.reduce((a, c) => (c.residual_mwh > a.residual_mwh ? c : a), cells[0]);
  const recurring_surplus_hours = cells
    .filter((c) => c.residual_mwh > 0)
    .reduce((a, c) => a + DAYS[c.month], 0);

  const headline =
    peak.residual_mwh > 0
      ? `Surplus recurs around ${hh(peak.hour)} in ${MONTHS[peak.month]} (+${peak.residual_mwh} MW median) — absorbing the recurring surplus takes about ${resp.storage_to_absorb_mwh} MWh of storage.`
      : "No recurring surplus window inside the three-year climatology — generation stays behind demand in every month.";

  return {
    ...resp,
    months,
    peak: { month: peak.month, hour: peak.hour, residual_mwh: peak.residual_mwh },
    recurring_surplus_hours,
    recurring_surplus_mwh: round(
      cells.reduce((a, c) => a + Math.max(0, c.residual_mwh) * DAYS[c.month], 0),
      0
    ),
    headline,
  };
}
