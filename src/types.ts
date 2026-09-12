export type Tech = "solar" | "wind";

/** POST /forecast — Option A: a registered site. */
export interface SiteForecastRequest {
  site_id: string;
  horizon_h?: number;
}

/** POST /forecast — Option B: cold start (any lat/lon, no history needed). */
export interface ColdStartForecastRequest {
  latitude: number;
  longitude: number;
  tech: Tech;
  capacity_mw: number;
  horizon_h?: number;
  tilt_deg?: number;
  azimuth_deg?: number;
  hub_height_m?: number;
}

export type ForecastRequest = SiteForecastRequest | ColdStartForecastRequest;

/** One hour of the forecast series. */
export interface HourPoint {
  valid_time_utc: string;
  horizon_h: number;
  p10_mw: number;
  p50_mw: number;
  p90_mw: number;
  clearsky_mw: number;
  physics_mw: number;
}

/** Exact shape of the /forecast response (input_output.md §6). */
export interface ForecastResponse {
  site_id: string;
  tech: Tech;
  issue_time_utc: string;
  capacity_mw: number;
  model_version: string;
  weather_source: string;
  location_is_estimated: boolean;
  points: HourPoint[];
}

/** GET /sites — one registered site. */
export interface SiteRecord {
  site_id: string;
  name: string;
  latitude: number;
  longitude: number;
  tech: Tech;
  capacity_mw: number;
  region: string;
  in_training_data: boolean;
}

export type SiteTechnology = "solar" | "wind";

/** Demand profile used by the balance analysis (hourly expected demand vs generation). */
export interface DemandHour {
  hour: number;
  demand_mw: number;
}