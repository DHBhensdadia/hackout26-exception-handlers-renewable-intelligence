import type { ForecastResponse, SiteRecord } from "@/types";
import { hourLabel, round } from "./util";

/**
 * Module 4 — operating conditions, and an honest account of what is missing.
 *
 * This module used to return a "risk index" seeded from `hash01(site_id)`, with a soiling
 * indicator that was a hash coin-flip. The numbers looked like model output and were not:
 * the same site always scored the same, because the score was a property of its name.
 *
 * There is no equipment reliability model behind this platform, and that is deliberate
 * rather than pending. Reliability analysis needs failure records, maintenance logs and
 * component histories, and none of that is public for these plants. The one available
 * substitute — outages inferred from gaps in SCADA — conflates genuine equipment failure
 * with curtailment, network constraint and economic withholding, and in a high-curtailment
 * region the latter dominate. A "failure risk" built that way would largely be measuring
 * negative prices. The project specification is explicit about this (§26): the system
 * should not claim that a failure can always be predicted.
 *
 * What *is* real is everything derivable from the forecast itself — how hard the plant is
 * being driven, how violently its output is about to change, how long it sits against its
 * export limit. Those are operating conditions, not failure probabilities, and they are
 * worth showing under that name. They are what survives here.
 */

export interface OperatingSignal {
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
  /** Observable stress indicators, each computed from the forecast series. */
  signals: OperatingSignal[];
  /** Quietest four-hour block — when intervention costs the least generation. */
  maintenanceWindow: MaintenanceWindow | null;
  /** Generation that would be lost if the plant were offline for that window. */
  windowLossMwh: number;
  /** Why there is no risk score here. Shown, not hidden in a tooltip. */
  unavailable: string;
}

const MAINTENANCE_HOURS = 4;

/** Quietest window in the horizon — the cheapest hours to take a plant offline. */
function maintenanceWindow(
  forecast: ForecastResponse
): { window: MaintenanceWindow; lossMwh: number } | null {
  const points = forecast.points;
  if (points.length < MAINTENANCE_HOURS) return null;

  let best = 0;
  let bestSum = Infinity;
  for (let i = 0; i <= points.length - MAINTENANCE_HOURS; i++) {
    const sum = points
      .slice(i, i + MAINTENANCE_HOURS)
      .reduce((total, p) => total + p.p50_mw, 0);
    if (sum < bestSum) {
      bestSum = sum;
      best = i;
    }
  }
  return {
    window: {
      start: hourLabel(points[best].valid_time_utc),
      end: hourLabel(points[best + MAINTENANCE_HOURS - 1].valid_time_utc),
      label: `quietest ${MAINTENANCE_HOURS} h in the horizon`,
    },
    lossMwh: round(bestSum, 1),
  };
}

export function reliabilityModel(
  forecast: ForecastResponse,
  site: SiteRecord
): ReliabilityResult {
  const points = forecast.points;
  const capacity = Math.max(forecast.capacity_mw, 1);
  const signals: OperatingSignal[] = [];

  // Hours spent at or near rated output. Sustained full-load running is a real operating
  // stress and is directly observable; it is not a failure probability.
  const nearRated = points.filter((p) => p.p50_mw >= 0.9 * capacity).length;
  signals.push({
    label: "Hours near rated output",
    value: `${nearRated} / ${points.length}`,
    note: "p50 above 90% of nameplate",
  });

  // Largest hour-to-hour swing. Ramps are what mechanical and inverter systems actually
  // have to follow.
  let maxRamp = 0;
  let rampAt = "";
  for (let i = 1; i < points.length; i++) {
    const delta = Math.abs(points[i].p50_mw - points[i - 1].p50_mw);
    if (delta > maxRamp) {
      maxRamp = delta;
      rampAt = points[i].valid_time_utc;
    }
  }
  signals.push({
    label: "Steepest ramp",
    value: `${round(maxRamp, 1)} MW/h`,
    note: rampAt ? `${round((100 * maxRamp) / capacity, 0)}% of nameplate · ${hourLabel(rampAt)}` : "—",
  });

  // Solar only: hours the forecast sits against the clear-sky ceiling, which is where
  // inverter clipping happens on an oversized array.
  if (site.tech === "solar") {
    const clipped = points.filter(
      (p) => p.clearsky_mw > 0 && p.p50_mw >= 0.98 * Math.min(p.clearsky_mw, capacity)
    ).length;
    signals.push({
      label: "Hours at the ceiling",
      value: `${clipped} / ${points.length}`,
      note: "output against the clear-sky limit",
    });
  } else {
    // Wind only: forecast spread is widest where the power curve is steepest, which is
    // also where a turbine's control system works hardest.
    const widest = points.reduce(
      (best, p) => (p.p90_mw - p.p10_mw > best.p90_mw - best.p10_mw ? p : best),
      points[0]
    );
    signals.push({
      label: "Least predictable hour",
      value: `${round(widest.p90_mw - widest.p10_mw, 1)} MW band`,
      note: hourLabel(widest.valid_time_utc),
    });
  }

  const maintenance = maintenanceWindow(forecast);

  return {
    signals,
    maintenanceWindow: maintenance?.window ?? null,
    windowLossMwh: maintenance?.lossMwh ?? 0,
    unavailable:
      "No equipment risk score is shown because there is no model behind one. Reliability " +
      "analysis needs failure records, maintenance logs and component histories, none of " +
      "which are public for these plants; outages inferred from SCADA gaps would conflate " +
      "equipment failure with curtailment and economic withholding. The figures above are " +
      "operating conditions read from the forecast, not failure probabilities.",
  };
}
