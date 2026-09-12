import type { ForecastResponse } from "@/types";
import type { BalanceResult } from "./balance";
import type { Scenario } from "./investment";

/** Cheap consistency checks for the derived layer. Returns human-readable violations. */
export function invariantViolations(
  forecast: ForecastResponse,
  balance: BalanceResult,
  scenarios: Scenario[] = []
): string[] {
  const v: string[] = [];

  for (const p of forecast.points) {
    if (!(p.p10_mw <= p.p50_mw && p.p50_mw <= p.p90_mw)) {
      v.push(`quantile order broken at ${p.valid_time_utc}`);
    }
    if (p.p10_mw < 0 || p.p90_mw > forecast.capacity_mw + 1e-6) {
      v.push(`value outside [0, capacity] at ${p.valid_time_utc}`);
    }
  }

  if (balance.surplusHours + balance.shortageHours !== balance.hours.length) {
    v.push("balance hours do not partition the horizon");
  }
  if (balance.surplusEnergy < 0 || balance.shortageEnergy < 0 || balance.unmetEnergy < 0 || balance.curtailEnergy < 0) {
    v.push("negative energy in balance");
  }

  for (const s of scenarios) {
    const sum = s.allocation.reduce((a, x) => a + x.cr, 0);
    if (Math.abs(sum - s.capex_cr) > s.capex_cr * 0.02) {
      v.push(`scenario ${s.key} allocation does not sum to budget`);
    }
    if (s.demand_met_pct < 0 || s.demand_met_pct > 100) {
      v.push(`scenario ${s.key} demand-met out of range`);
    }
  }

  return v;
}
