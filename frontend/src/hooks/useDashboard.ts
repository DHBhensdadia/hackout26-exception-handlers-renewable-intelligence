import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { forecast, isAbortError, listSites } from "@/api/client";
import { config } from "@/config";
import type { ForecastResponse, SiteRecord } from "@/types";
import { toJson, toRequest, type DashboardForm } from "@/lib/dashboardForm";
import {
  capacityModel,
  computeBalance,
  invariantViolations,
  reliabilityModel,
  seasonalPattern,
  storageModel,
  type BalanceResult,
  type CapacityResult,
  type ReliabilityResult,
  type SeasonalResult,
  type StorageModel,
} from "@/lib/derive";

export interface DerivedDashboard {
  site: SiteRecord;
  storage: StorageModel;
  balance: BalanceResult;
  reliability: ReliabilityResult;
  seasonal: SeasonalResult;
  capacity: CapacityResult;
}

function coldSite(form: DashboardForm, id?: string, tech?: SiteRecord["tech"], capacity?: number): SiteRecord {
  return {
    site_id: id ?? `adhoc-${form.latitude},${form.longitude}`,
    name: "Cold start",
    latitude: form.latitude,
    longitude: form.longitude,
    tech: tech ?? form.tech,
    capacity_mw: capacity ?? form.capacity_mw,
    region: "Ad-hoc coordinates",
    in_training_data: false,
  };
}

/**
 * One orchestration hook for the decision console: registry, form state, the
 * forecast run, and the deterministic derived models that consume it.
 * In-flight runs are cancelled so a stale response can never overwrite a newer one.
 */
export function useDashboard() {
  const [sites, setSites] = useState<SiteRecord[]>([]);
  const [form, setForm] = useState<DashboardForm>({
    mode: "site",
    site_id: "GJ-SOLAR-CHARANKA",
    tech: "solar",
    capacity_mw: 50,
    latitude: 23.03,
    longitude: 72.57,
    horizon_h: config.HORIZON_DEFAULT,
  });
  const [result, setResult] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const booted = useRef(false);
  const runCtrl = useRef<AbortController | null>(null);

  const patch = useCallback((p: Partial<DashboardForm>) => setForm((f) => ({ ...f, ...p })), []);

  const runWith = useCallback((f: DashboardForm) => {
    runCtrl.current?.abort();
    const ctrl = new AbortController();
    runCtrl.current = ctrl;

    setLoading(true);
    setError(null);
    forecast(toRequest(f), ctrl.signal)
      .then((res) => {
        if (!ctrl.signal.aborted) setResult(res);
      })
      .catch((e: unknown) => {
        if (!isAbortError(e)) setError(e instanceof Error ? e.message : "Forecast failed.");
      })
      .finally(() => {
        if (runCtrl.current === ctrl) setLoading(false);
      });
  }, []);

  const run = useCallback(() => runWith(form), [form, runWith]);

  const pickSite = useCallback(
    (s: SiteRecord) => {
      const next: DashboardForm = {
        ...form,
        mode: "site",
        site_id: s.site_id,
        tech: s.tech,
        capacity_mw: s.capacity_mw,
        latitude: s.latitude,
        longitude: s.longitude,
      };
      setForm(next);
      runWith(next);
    },
    [form, runWith]
  );

  useEffect(() => {
    const ctrl = new AbortController();
    listSites(ctrl.signal)
      .then(setSites)
      .catch((e: unknown) => {
        if (!isAbortError(e)) setError("Could not load the site registry.");
      });
    return () => ctrl.abort();
  }, []);

  // First run once the registry arrives, so the console is never blank.
  useEffect(() => {
    if (!booted.current && sites.length) {
      booted.current = true;
      runWith(form);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sites.length]);

  // Cancel any in-flight run when the console unmounts.
  useEffect(() => () => runCtrl.current?.abort(), []);

  /** The site record aligned to the last run (capacity/tech from the response). */
  const site = useMemo<SiteRecord | null>(() => {
    if (result) {
      const base = sites.find((s) => s.site_id === result.site_id);
      return base
        ? { ...base, tech: result.tech, capacity_mw: result.capacity_mw }
        : coldSite(form, result.site_id, result.tech, result.capacity_mw);
    }
    if (form.mode === "cold") return coldSite(form);
    return sites.find((s) => s.site_id === form.site_id) ?? null;
  }, [result, sites, form]);

  const derived = useMemo<DerivedDashboard | null>(() => {
    if (!result || !site) return null;
    const storage = storageModel(site);
    return {
      site,
      storage,
      balance: computeBalance(result, site, storage),
      reliability: reliabilityModel(result, site),
      seasonal: seasonalPattern(site),
      capacity: capacityModel(result, site),
    };
  }, [result, site]);

  const jsonPreview = useMemo(() => toJson(form), [form]);

  // Dev-only consistency check for the derived layer (spec: no silent bad numbers).
  useEffect(() => {
    if (!import.meta.env.DEV || !result || !derived) return;
    const violations = invariantViolations(result, derived.balance);
    if (violations.length) console.warn("[derive] invariant violations:", violations);
  }, [result, derived]);

  return { sites, form, patch, run, pickSite, result, loading, error, derived, jsonPreview };
}
