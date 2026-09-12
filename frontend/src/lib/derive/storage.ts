import type { SiteRecord } from "@/types";
import { hash01 } from "./util";

/** First-class storage model for a site (spec §14). */
export interface StorageModel {
  capacity_mwh: number;
  soc_pct: number;
  available_mwh: number;
  headroom_mwh: number;
  power_mw: number;
}

/**
 * Deterministic storage model derived from the site rating.
 * Storage is treated as a planning variable, not an add-on.
 */
export function storageModel(site: SiteRecord): StorageModel {
  const h = hash01(site.site_id + ":storage");
  const hours = 2.2 + h * 2.0; // 2.2–4.2 h of rated capacity
  const capacity = Math.round(site.capacity_mw * hours);
  const soc = 0.45 + h * 0.3; // 45–75 % charged
  return {
    capacity_mwh: capacity,
    soc_pct: Math.round(soc * 100),
    available_mwh: Math.round(capacity * soc),
    headroom_mwh: Math.round(capacity * (1 - soc)),
    power_mw: Math.round(site.capacity_mw * 0.5),
  };
}
