import { clamp, hash01 } from "./util";

/**
 * Regional climatology — the stand-in for the on-disk AEMO history described in
 * model-outputs-and-visualisation.md §2.2/§5.3. Deterministic per region and
 * hour, so the Seasonal module computes a real month x hour pattern over a
 * three-year series instead of deriving it from a site-id hash.
 */

export interface RegionProfile {
  region_id: string;
  solar_capacity_mw: number;
  wind_capacity_mw: number;
  demand_peak_mw: number;
  /** Local offset from UTC, hours (AEMO regions sit at +9.5 to +11). */
  utc_offset_h: number;
  /** Tasmania carries a genuine morning peak as well as the evening one. */
  double_peak?: boolean;
}

export const REGION_PROFILES: Record<string, RegionProfile> = {
  QLD1: { region_id: "QLD1", solar_capacity_mw: 5200, wind_capacity_mw: 1600, demand_peak_mw: 7200, utc_offset_h: 10 },
  NSW1: { region_id: "NSW1", solar_capacity_mw: 6800, wind_capacity_mw: 2600, demand_peak_mw: 9800, utc_offset_h: 10 },
  SA1: { region_id: "SA1", solar_capacity_mw: 3300, wind_capacity_mw: 2100, demand_peak_mw: 2100, utc_offset_h: 9.5 },
  TAS1: { region_id: "TAS1", solar_capacity_mw: 450, wind_capacity_mw: 1200, demand_peak_mw: 1150, utc_offset_h: 10, double_peak: true },
  VIC1: { region_id: "VIC1", solar_capacity_mw: 4600, wind_capacity_mw: 3400, demand_peak_mw: 6900, utc_offset_h: 10 },
};

/** Southern-hemisphere solar: peak in December, trough in June. */
const SOLAR_SEASON = [1.05, 1.0, 0.9, 0.78, 0.68, 0.6, 0.62, 0.7, 0.82, 0.92, 1.0, 1.06];
/** Wind: stronger through the southern winter. */
const WIND_SEASON = [0.8, 0.82, 0.9, 1.0, 1.1, 1.18, 1.2, 1.15, 1.05, 0.95, 0.85, 0.8];
/** Demand: summer air-conditioning and a winter heating shoulder. */
const DEMAND_SEASON = [1.06, 1.05, 0.98, 0.9, 0.88, 0.94, 0.96, 0.94, 0.9, 0.92, 0.98, 1.04];

/** One typical day, local hour 0-23, normalised to an evening peak at 19:00. */
const DEMAND_DAY = [0.62, 0.58, 0.56, 0.55, 0.55, 0.58, 0.66, 0.72, 0.76, 0.78, 0.78, 0.77, 0.76, 0.75, 0.75, 0.77, 0.82, 0.9, 0.97, 1.0, 0.96, 0.88, 0.76, 0.68];
const DEMAND_DAY_DOUBLE = [0.7, 0.65, 0.62, 0.6, 0.62, 0.68, 0.8, 0.9, 0.95, 0.92, 0.86, 0.82, 0.8, 0.8, 0.82, 0.86, 0.9, 0.94, 0.92, 0.88, 0.82, 0.78, 0.74, 0.72];

export function localHour(profile: RegionProfile, date: Date): number {
  return (date.getUTCHours() + profile.utc_offset_h + 24) % 24;
}

function diurnal(hour: number, table: number[]): number {
  const i = Math.floor(hour) % 24;
  const j = (i + 1) % 24;
  const f = hour - Math.floor(hour);
  return table[i] * (1 - f) + table[j] * f;
}

/** Clear-sky generation as a fraction of installed capacity, local hour. */
export function solarDiurnal(hour: number): number {
  const d = Math.abs(hour - 12.5);
  if (d >= 6.25) return 0;
  return Math.cos((d / 6.25) * (Math.PI / 2));
}

export function windDiurnal(hour: number): number {
  return clamp(0.5 + 0.22 * Math.cos(((hour - 15) / 24) * Math.PI * 2), 0.2, 1);
}

/** Median-ish renewable output for a region at an instant, MW. */
export function renewableAt(profile: RegionProfile, date: Date): number {
  const hour = localHour(profile, date);
  const month = date.getUTCMonth();
  const sun = solarDiurnal(hour) * SOLAR_SEASON[month] * profile.solar_capacity_mw;
  const wind = windDiurnal(hour) * WIND_SEASON[month] * profile.wind_capacity_mw;
  const jitter = 0.96 + hash01(`${profile.region_id}:${date.getUTCMonth()}:${hour}:re`) * 0.08;
  return sun + wind * jitter;
}

/** Expected demand for a region at an instant, MW. */
export function demandAt(profile: RegionProfile, date: Date): number {
  const hour = localHour(profile, date);
  const month = date.getUTCMonth();
  const table = profile.double_peak ? DEMAND_DAY_DOUBLE : DEMAND_DAY;
  const jitter = 0.98 + hash01(`${profile.region_id}:${date.getUTCMonth()}:${hour}:dem`) * 0.04;
  return profile.demand_peak_mw * diurnal(hour, table) * DEMAND_SEASON[month] * jitter;
}

/** Residual load: negative is surplus, positive is unmet by renewables. */
export function residualAt(profile: RegionProfile, date: Date): number {
  return demandAt(profile, date) - renewableAt(profile, date);
}

/** Fixed history start so every run sees the same three years. */
export const HISTORY_START_UTC = Date.UTC(2022, 0, 1);

export interface HistoryStep {
  date: Date;
  month: number;
  hour: number;
  residual_mwh: number;
}

/** Iterate three years of hourly residuals (the seasonal grid's raw input). */
export function forEachHistoryStep(profile: RegionProfile, fn: (step: HistoryStep) => void, years = 3): void {
  const hours = years * 8760;
  for (let i = 0; i < hours; i++) {
    const date = new Date(HISTORY_START_UTC + i * 3_600_000);
    fn({ date, month: date.getUTCMonth(), hour: date.getUTCHours(), residual_mwh: residualAt(profile, date) });
  }
}
