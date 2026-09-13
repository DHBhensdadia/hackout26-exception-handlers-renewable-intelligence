import { config } from "@/config";
import { mockApi } from "./mock";
import { seasonalCells } from "@/lib/derive/seasonal";
import { summarizeDemand, type DemandResult } from "@/lib/derive";
import type {
  BalanceResponse,
  ColdStartForecastRequest,
  DemandResponse,
  ForecastRequest,
  ForecastResponse,
  RegionCapacity,
  RegionRecord,
  SeasonalCell,
  SeasonalResponse,
  SiteForecastRequest,
  SiteRecord,
  Tech,
} from "../types";

/**
 * Single entry point for dashboard data. When USE_MOCK is true this returns
 * schema-exact deterministic seed data; when false it issues real HTTP calls
 * to the FastAPI backend from input_output.md.
 *
 * Every real call is cancellable and time-boxed so rapid "Run forecast"
 * presses cannot race a stale response over a fresh one.
 */

const REQUEST_TIMEOUT_MS = 15_000;

/** Detect an aborted request so callers can ignore it silently. */
export function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

function friendlyError(status: number): string {
  if (status === 404) return "The service could not find that resource (404).";
  if (status === 422) return "The request was rejected by the server (422). Check the inputs.";
  if (status >= 500) return "The forecasting service is unavailable right now. Try again shortly.";
  return `Request failed (${status}). Please try again.`;
}

async function fetchJson<T>(url: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal });
    if (!res.ok) throw new Error(friendlyError(res.status));
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

function realForecast(
  req: ForecastRequest & { capacity_mw: number; tech: Tech },
  signal?: AbortSignal
): Promise<ForecastResponse> {
  return fetchJson<ForecastResponse>(
    `${config.API_BASE_URL}/forecast`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    },
    signal
  );
}

function realListSites(signal?: AbortSignal): Promise<SiteRecord[]> {
  return fetchJson<SiteRecord[]>(`${config.API_BASE_URL}/sites`, {}, signal);
}

function realListRegions(signal?: AbortSignal): Promise<RegionRecord[]> {
  return fetchJson<RegionRecord[]>(`${config.API_BASE_URL}/regions`, {}, signal);
}

function realDemand(region: RegionRecord, horizonH: number, signal?: AbortSignal): Promise<DemandResult> {
  return fetchJson<DemandResponse>(
    `${config.API_BASE_URL}/demand`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region_id: region.region_id, horizon_h: horizonH }),
    },
    signal
  ).then((resp) => summarizeDemand({ ...resp, source: "api" }, region, new Date().getUTCFullYear()));
}

export function forecast(
  req: ForecastRequest & { capacity_mw: number; tech: Tech },
  signal?: AbortSignal
): Promise<ForecastResponse> {
  return config.USE_MOCK ? mockApi.forecast(req, signal) : realForecast(req, signal);
}

export function listSites(signal?: AbortSignal): Promise<SiteRecord[]> {
  return config.USE_MOCK ? mockApi.listSites(signal) : realListSites(signal);
}

export function listRegions(signal?: AbortSignal): Promise<RegionRecord[]> {
  return config.USE_MOCK ? mockApi.listRegions(signal) : realListRegions(signal);
}

/**
 * Regional demand band. `POST /demand` is not built yet, so a real-mode 404
 * degrades to the same deterministic model, labelled `source: "modelled"`.
 */
export function demandForRegion(
  region: RegionRecord,
  horizonH: number,
  signal?: AbortSignal
): Promise<DemandResult> {
  if (config.USE_MOCK) return mockApi.demand(region, horizonH, signal);
  return realDemand(region, horizonH, signal).catch((e: unknown) => {
    if (isAbortError(e)) throw e;
    return mockApi.demand(region, horizonH, signal);
  });
}

export type { SiteForecastRequest, ColdStartForecastRequest, ForecastRequest };


/**
 * Regional balance: generation against demand, as calibrated probabilities.
 *
 * Distinct from the client-side `computeBalance` in `lib/derive`, which models a single
 * site against a synthetic demand curve. This is the whole region against real metered
 * demand, aggregated from 200 coherent scenarios - and crucially not a sum of per-site
 * quantiles, which would overstate regional uncertainty by roughly threefold.
 *
 * There is no mock. The shape is large and the point of it is that the numbers are real;
 * a hand-written stand-in would be the one thing this panel must not show. When the API is
 * unavailable the panel says so instead.
 */
export function regionalBalance(
  region: string,
  horizonH: number,
  signal?: AbortSignal
): Promise<BalanceResponse> {
  return fetchJson<BalanceResponse>(
    `${config.API_BASE_URL}/balance`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region, horizon_h: horizonH }),
    },
    signal
  );
}

/**
 * Installed capacity per region, as the backend serves it.
 *
 * Distinct from `listRegions` above, which is mock-aware and returns the regional *model*
 * metadata the demand and seasonal panels read. Two different payloads from one path, so
 * they are two functions rather than one with a mode flag.
 */
export function listRegionCapacity(signal?: AbortSignal): Promise<RegionCapacity[]> {
  return fetchJson<RegionCapacity[]>(`${config.API_BASE_URL}/regions`, {}, signal);
}


/** What `GET /seasonal/{region}` actually returns, before it is adapted. */
interface SeasonalApiResponse {
  region: string;
  years_of_history: number;
  data_mode: string;
  grids: Record<string, (number | null)[][]>;
  storage: { targets: Record<string, { energy_mwh: number } | null> };
}

/**
 * Seasonal climatology from the backend, adapted to the shape the panel consumes.
 *
 * Two conventions flip on the way across, and both would be silent if missed:
 *
 * The API's `residual_mw` is `demand - renewable`, so **negative means surplus**. The panel
 * treats `residual_mwh > 0` as surplus. The sign is inverted here, once, rather than in
 * each component that reads it.
 *
 * The API indexes months 1-12; the panel indexes 0-11.
 *
 * `storage_to_absorb_mwh` is read off the 80% capture target rather than the 95% one: the
 * curve knees hard, and the last few percent of surplus costs several times the battery
 * that the first eighty do.
 */
function realSeasonal(region: RegionRecord, signal?: AbortSignal): Promise<SeasonalResponse> {
  return fetchJson<SeasonalApiResponse>(
    `${config.API_BASE_URL}/seasonal/${encodeURIComponent(region.region_id)}`,
    {},
    signal
  ).then((resp) => {
    const residual = resp.grids.residual_mw ?? [];
    const share = resp.grids.surplus_share ?? [];
    const cells: SeasonalCell[] = [];

    for (let m = 0; m < 12; m++) {
      for (let h = 0; h < 24; h++) {
        const raw = residual[m]?.[h];
        cells.push({
          month: m,
          hour: h,
          // Sign flipped: surplus-positive, which is what the panel expects.
          residual_mwh: raw == null ? 0 : Math.round(-raw),
          surplus_pct: share[m]?.[h] ?? 0,
        });
      }
    }

    const target = resp.storage?.targets?.["80pct"];
    return {
      region_id: resp.region,
      window_years: Math.round(resp.years_of_history),
      source: `AEMO ${resp.data_mode} history, ${resp.years_of_history.toFixed(1)} years`,
      cells,
      storage_to_absorb_mwh: target ? Math.round(target.energy_mwh) : 0,
    };
  });
}

/**
 * Seasonal patterns. Falls back to the in-browser climatology if the endpoint is absent,
 * the same way `demandForRegion` does, so the demo survives a backend that is not running.
 */
export function seasonalForRegion(
  region: RegionRecord,
  signal?: AbortSignal
): Promise<SeasonalResponse> {
  if (config.USE_MOCK) return Promise.resolve(seasonalCells(region));
  return realSeasonal(region, signal).catch((e: unknown) => {
    if (isAbortError(e)) throw e;
    return seasonalCells(region);
  });
}
