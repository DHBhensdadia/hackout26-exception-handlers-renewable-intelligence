import type { ColdStartForecastRequest, ForecastRequest, SiteForecastRequest, Tech } from "@/types";

/**
 * The dashboard's run configuration model plus its serializers. Kept in `lib`
 * so the orchestration hook never has to import from a presentational
 * component.
 */
export interface DashboardForm {
  mode: "site" | "cold";
  site_id: string;
  tech: Tech;
  capacity_mw: number;
  latitude: number;
  longitude: number;
  horizon_h: number;
  tilt_deg?: number;
  azimuth_deg?: number;
  hub_height_m?: number;
}

/** Collapse an input form into a POST /forecast request. */
export function toRequest(form: DashboardForm): ForecastRequest & { capacity_mw: number; tech: Tech } {
  const base = { horizon_h: form.horizon_h, capacity_mw: form.capacity_mw, tech: form.tech };
  if (form.mode === "site") {
    return { site_id: form.site_id, ...base } as SiteForecastRequest & { capacity_mw: number; tech: Tech };
  }
  const cold: ColdStartForecastRequest = {
    latitude: form.latitude,
    longitude: form.longitude,
    tech: form.tech,
    capacity_mw: form.capacity_mw,
    horizon_h: form.horizon_h,
    tilt_deg: form.tilt_deg,
    azimuth_deg: form.azimuth_deg,
    hub_height_m: form.hub_height_m,
  };
  return cold as ForecastRequest & { capacity_mw: number; tech: Tech };
}

/** Compose the JSON preview box for the request panel. */
export function toJson(view: DashboardForm): string {
  return JSON.stringify(toRequest(view), null, 2);
}
