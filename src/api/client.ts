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
 */

async function realForecast(req: ForecastRequest & { capacity_mw: number; tech: Tech }): Promise<ForecastResponse> {
  const res = await fetch(`${config.API_BASE_URL}/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`Forecast failed (${res.status}): ${await res.text()}`);
  }
  return (await res.json()) as ForecastResponse;
}

async function realListSites(): Promise<SiteRecord[]> {
  const res = await fetch(`${config.API_BASE_URL}/sites`);
  if (!res.ok) {
    throw new Error(`Sites failed (${res.status})`);
  }
  return (await res.json()) as SiteRecord[];
}

export function forecast(req: ForecastRequest & { capacity_mw: number; tech: Tech }): Promise<ForecastResponse> {
  return config.USE_MOCK ? mockApi.forecast(req) : realForecast(req);
}

export function listSites(): Promise<SiteRecord[]> {
  return config.USE_MOCK ? mockApi.listSites() : realListSites();
}

export type { SiteForecastRequest, ColdStartForecastRequest, ForecastRequest };