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


/* ------------------------------------------------------------------ /balance */

/**
 * One hour of the regional balance. Computed by the backend from 200 coherent
 * scenarios, not derived in the browser.
 *
 * `residual_load = demand - renewable`, so **negative residual means surplus** —
 * more renewable output drives the number down.
 */
export interface BalanceHourPoint {
  valid_time_utc: string;
  horizon_h: number;
  region: string;
  demand_p50_mw: number;
  renewable_p10_mw: number;
  renewable_p50_mw: number;
  renewable_p90_mw: number;
  residual_p10_mw: number;
  residual_p50_mw: number;
  residual_p90_mw: number;
  /** Probability generation exceeds demand. Not complementary with p_shortage. */
  p_surplus: number;
  p_shortage: number;
  /** Probability-weighted, zero where the event does not occur. Sums into energy. */
  expected_surplus_mw: number;
  expected_shortage_mw: number;
  /** Size of the event *if* it happens. expected = p x conditional. */
  conditional_surplus_mw: number;
  conditional_shortage_mw: number;
  expected_surplus_mwh: number;
  expected_shortage_mwh: number;
  recommended_action:
    | "cover_shortage"
    | "hold_reserve"
    | "absorb_surplus"
    | "prepare_to_absorb"
    | "normal";
}

/** A contiguous run of 2+ hours above 50% probability. */
export interface BalanceEvent {
  kind: "surplus" | "shortage";
  from_utc: string;
  to_utc: string;
  hours: number;
  peak_probability: number;
  energy_mwh: number;
}

/** What actually happened over the replayed window. */
export interface BalanceActual {
  valid_time_utc: string;
  renewable_mw: number;
  demand_mw: number;
  residual_mw: number;
}

export interface BalanceResponse {
  region: string;
  issue_time_utc: string;
  model_version: string;
  n_scenarios: number;
  dispatchable_headroom_mw: number;
  technologies: string[];
  /** "replay" while the market ingest lags the calendar. See data_note. */
  data_mode: string;
  data_note: string;
  horizon_h: number;
  points: BalanceHourPoint[];
  events: BalanceEvent[];
  actual: BalanceActual[];
}

/** GET /regions — one market region. */
export interface RegionRecord {
  region: string;
  technologies: Record<string, { sites: number; capacity_mw: number }>;
  total_capacity_mw: number;
  balance_available: boolean;
}
