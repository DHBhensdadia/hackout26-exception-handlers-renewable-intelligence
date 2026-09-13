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

/** GET /regions — metadata for the regional demand model (measured accuracy). */
export interface RegionRecord {
  region_id: string;
  name: string;
  nmae_pct: number;
  coverage_pct: number;
  balance_available: boolean;
  caveat?: string;
  /** Dispatchable headroom, MW — the ceiling above which coverage is scarce. */
  headroom_mw: number;
}

/** POST /demand — one hour of a regional demand band. */
export interface DemandPoint {
  valid_time_utc: string;
  horizon_h: number;
  p10_mw: number;
  p50_mw: number;
  p90_mw: number;
}

/** POST /demand response (docs/api-contract.md semantics). */
export interface DemandResponse {
  region_id: string;
  data_mode: "replay" | "live";
  model_version: string;
  nmae_pct: number;
  coverage_pct: number;
  points: DemandPoint[];
  /** "api" when served by the backend, "modelled" when computed locally. */
  source: "api" | "modelled";
}

/** One month x hour cell of the seasonal climatology. */
export interface SeasonalCell {
  month: number;
  hour: number;
  residual_mwh: number;
  surplus_pct: number;
}

/** GET /seasonal/{region} response (endpoint currently cut). */
export interface SeasonalResponse {
  region_id: string;
  window_years: number;
  source: string;
  cells: SeasonalCell[];
  storage_to_absorb_mwh: number;
}

