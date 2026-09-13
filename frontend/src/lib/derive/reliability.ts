import type { ForecastResponse, SiteRecord } from "@/types";
import { clamp, hash01, hourLabel, round } from "./util";

export interface ReliabilityDriver {
  label: string;
  value: string;
  note: string;
}

export interface MaintenanceWindow {
  start: string;
  end: string;
  label: string;
}

export interface ReliabilityResult {
  risk: number;
  band: "low" | "moderate" | "elevated";
  tone: "ok" | "warn" | "bad";
  drivers: ReliabilityDriver[];
  expectedLossMwh: number;
  maintenanceWindow: MaintenanceWindow | null;
  note: string;
}

const bandOf = (risk: number): Pick<ReliabilityResult, "band" | "tone"> =>
  risk < 0.25
    ? { band: "low", tone: "ok" }
    : risk < 0.42
      ? { band: "moderate", tone: "warn" }
      : { band: "elevated", tone: "bad" };

/** Lowest 4-hour generation window inside the horizon — the safest maintenance slot. */
function maintenanceWindow(forecast: ForecastResponse): MaintenanceWindow | null {
  const pts = forecast.points;
  if (pts.length < 4) return null;
  let best = 0;
  let bestSum = Infinity;
  for (let i = 0; i <= pts.length - 4; i++) {
    const sum = pts.slice(i, i + 4).reduce((a, p) => a + p.p50_mw, 0);
    if (sum < bestSum) {
      bestSum = sum;
      best = i;
    }
  }
  return {
    start: hourLabel(pts[best].valid_time_utc),
    end: hourLabel(pts[best + 3].valid_time_utc),
    label: `lowest output · ${round(bestSum, 1)} MWh over 4 h`,
  };
}

/**
 * Module 4 — equipment reliability & failure risk (spec §10).
 * Risk scoring and preparedness, never a claim of failure prediction.
 */
export function reliabilityModel(forecast: ForecastResponse, site: SiteRecord): ReliabilityResult {
  const pts = forecast.points;
  const cap = site.capacity_mw;
  const base = 0.12 + hash01(site.site_id + ":risk") * 0.14;
  const drivers: ReliabilityDriver[] = [];
  let risk = base;

  if (site.tech === "wind") {
    let maxJump = 0;
    let jumpHour = 0;
    for (let i = 1; i < pts.length; i++) {
      const jump = Math.abs(pts[i].physics_mw - pts[i - 1].physics_mw);
      if (jump > maxJump) {
        maxJump = jump;
        jumpHour = i;
      }
    }
    const nearRated = pts.filter((p) => p.p90_mw > cap * 0.9).length;
    drivers.push(
      { label: "Gust exposure", value: `${maxJump.toFixed(1)} MW/h`, note: `peak swing at +${jumpHour} h` },
      { label: "Near-rated hours", value: `${nearRated} h`, note: "p90 within 10 % of capacity" },
      {
        label: "Cut-out proximity",
        value: nearRated > 6 ? "elevated" : "low",
        note: "turbine protection threshold",
      },
    );
    risk += (nearRated / Math.max(1, pts.length)) * 0.28 + (maxJump / Math.max(1, cap)) * 0.22;
  } else {
    const peak = pts.reduce((a, b) => (b.clearsky_mw > a.clearsky_mw ? b : a), pts[0]);
    const derate = peak.clearsky_mw > 0 ? 1 - peak.p50_mw / peak.clearsky_mw : 0;
    const clipping = pts.filter((p) => p.clearsky_mw > cap * 0.98).length;
    drivers.push(
      { label: "Heat / cloud derate", value: `${(derate * 100).toFixed(0)} %`, note: "gap vs clearsky at peak hour" },
      { label: "Clipping hours", value: `${clipping} h`, note: "clearsky above inverter limit" },
      {
        label: "Soiling risk",
        value: hash01(site.site_id + ":soiling") > 0.5 ? "moderate" : "low",
        note: "seasonal dust / monsoon wash-off",
      },
    );
    risk += Math.min(0.2, derate * 0.2) + (clipping / Math.max(1, pts.length)) * 0.1;
  }

  risk = clamp(risk, 0.05, 0.6);
  const { band, tone } = bandOf(risk);
  const expectedLossMwh = round(cap * risk * 0.08 * (pts.length / 24), 1);
  const window = maintenanceWindow(forecast);

  return {
    risk: round(risk, 2),
    band,
    tone,
    drivers,
    expectedLossMwh,
    maintenanceWindow: window,
    note: "Risk scoring only — the system does not claim to predict failures.",
  };
}
