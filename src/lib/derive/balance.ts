import type { ForecastResponse, HourPoint, SiteRecord } from "@/types";
import type { StorageModel } from "./storage";
import { clamp, DEMAND_CURVE, hash01, round } from "./util";

export interface BalanceHour {
  i: number;
  valid_time_utc: string;
  horizon_h: number;
  gen_p10: number;
  gen_p50: number;
  gen_p90: number;
  demand: number;
  net: number;
  state: "surplus" | "shortage";
  action: "charge" | "discharge" | "hold";
  stored: number;
  curtailed: number;
  unmet: number;
  soc_mwh: number;
}

export interface BalanceVerdict {
  key: "balanced" | "surplus" | "shortage";
  label: string;
  tone: "ok" | "warn" | "bad";
  action: string;
  detail: string;
}

export interface BalanceResult {
  hours: BalanceHour[];
  demand: number[];
  surplusHours: number;
  shortageHours: number;
  surplusEnergy: number;
  shortageEnergy: number;
  chargeEnergy: number;
  curtailEnergy: number;
  unmetEnergy: number;
  worstShortage: BalanceHour | null;
  worstSurplus: BalanceHour | null;
  peakDemand: number;
  demandMetPct: number;
  verdict: BalanceVerdict;
}

/** Deterministic expected-demand curve for a site, hour by hour. */
export function demandForSite(site: SiteRecord, points: HourPoint[]): number[] {
  const factor = 0.36 + hash01(site.site_id + ":demand") * 0.16; // 36–52 % of rating
  return points.map((p) => {
    const hour = new Date(p.valid_time_utc).getUTCHours();
    const jitter = 0.97 + hash01(`${site.site_id}:${hour}`) * 0.06;
    return round(site.capacity_mw * factor * (DEMAND_CURVE[hour] / 95) * jitter, 2);
  });
}

/**
 * Module 2 — generation · demand · storage balance (spec §8).
 * Dispatches storage hour by hour; curtailment is the residue after charging.
 */
export function computeBalance(forecast: ForecastResponse, site: SiteRecord, storage: StorageModel): BalanceResult {
  const demand = demandForSite(site, forecast.points);
  const hours: BalanceHour[] = [];

  let soc = storage.available_mwh;
  let surplusHours = 0;
  let shortageHours = 0;
  let surplusEnergy = 0;
  let shortageEnergy = 0;
  let chargeEnergy = 0;
  let curtailEnergy = 0;
  let unmetEnergy = 0;

  forecast.points.forEach((p, i) => {
    const gen = p.p50_mw;
    const d = demand[i];
    const net = round(gen - d, 2);

    let action: BalanceHour["action"] = "hold";
    let stored = 0;
    let curtailed = 0;
    let unmet = 0;
    let state: BalanceHour["state"];

    if (net >= 0) {
      state = "surplus";
      surplusHours++;
      surplusEnergy += net;
      stored = Math.min(net, storage.power_mw, storage.capacity_mwh - soc);
      curtailed = round(net - stored, 2);
      soc += stored;
      chargeEnergy += stored;
      curtailEnergy += curtailed;
      action = stored > 0.05 ? "charge" : "hold";
    } else {
      state = "shortage";
      shortageHours++;
      shortageEnergy += -net;
      const deficit = -net;
      const discharge = Math.min(deficit, storage.power_mw, soc);
      unmet = round(deficit - discharge, 2);
      soc -= discharge;
      unmetEnergy += unmet;
      action = discharge > 0.05 ? "discharge" : "hold";
    }

    const row: BalanceHour = {
      i,
      valid_time_utc: p.valid_time_utc,
      horizon_h: p.horizon_h,
      gen_p10: p.p10_mw,
      gen_p50: p.p50_mw,
      gen_p90: p.p90_mw,
      demand: d,
      net,
      state,
      action,
      stored: round(stored, 2),
      curtailed,
      unmet,
      soc_mwh: round(soc, 0),
    };
    hours.push(row);
  });

  const shortages = hours.filter((h) => h.state === "shortage");
  const surpluses = hours.filter((h) => h.state === "surplus");
  const worstShortage = shortages.length ? shortages.reduce((a, b) => (b.net < a.net ? b : a)) : null;
  const worstSurplus = surpluses.length ? surpluses.reduce((a, b) => (b.net > a.net ? b : a)) : null;

  const n = Math.max(1, hours.length);
  const demandMetPct = Math.round(((n - hours.filter((h) => h.unmet > 0).length) / n) * 100);
  const peakDemand = Math.max(...demand, 1);

  let verdict: BalanceVerdict;
  if (unmetEnergy > 0.5) {
    const gap = worstShortage ? Math.abs(worstShortage.net) : 0;
    verdict = {
      key: "shortage",
      label: "Shortage risk",
      tone: "bad",
      action: "Discharge storage first; hold backup for the worst window",
      detail: `${unmetEnergy.toFixed(1)} MWh unmet after storage · worst gap ${gap.toFixed(1)} MW`,
    };
  } else if (surplusHours / n > 0.35) {
    verdict = {
      key: "surplus",
      label: "Surplus risk",
      tone: "warn",
      action: "Charge storage during the surplus window; curtail only the residue",
      detail: `${curtailEnergy.toFixed(1)} MWh beyond storage · ${chargeEnergy.toFixed(1)} MWh storeable`,
    };
  } else {
    verdict = {
      key: "balanced",
      label: "Balanced",
      tone: "ok",
      action: "Hold normal reserve — forecast covers expected demand",
      detail: `${demandMetPct}% of hours covered at p50 · ${chargeEnergy.toFixed(1)} MWh stored`,
    };
  }

  return {
    hours,
    demand,
    surplusHours,
    shortageHours,
    surplusEnergy: round(surplusEnergy, 1),
    shortageEnergy: round(shortageEnergy, 1),
    chargeEnergy: round(chargeEnergy, 1),
    curtailEnergy: round(curtailEnergy, 1),
    unmetEnergy: round(unmetEnergy, 1),
    worstShortage,
    worstSurplus,
    peakDemand: round(peakDemand, 1),
    demandMetPct: clamp(demandMetPct, 0, 100),
    verdict,
  };
}
