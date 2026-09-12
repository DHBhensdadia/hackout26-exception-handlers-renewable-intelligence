import { config } from "@/config";
import { mockApi } from "./mock";
import type {
  ColdStartForecastRequest,
  ForecastRequest,
  ForecastResponse,
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

export function forecast(
  req: ForecastRequest & { capacity_mw: number; tech: Tech },
  signal?: AbortSignal
): Promise<ForecastResponse> {
  return config.USE_MOCK ? mockApi.forecast(req, signal) : realForecast(req, signal);
}

export function listSites(signal?: AbortSignal): Promise<SiteRecord[]> {
  return config.USE_MOCK ? mockApi.listSites(signal) : realListSites(signal);
}

export type { SiteForecastRequest, ColdStartForecastRequest, ForecastRequest };
