import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  demandForRegion,
  forecast,
  isAbortError,
  listRegions,
  listSites,
  seasonalForRegion,
} from "@/api/client";
import { config } from "@/config";
import type { ForecastResponse, RegionRecord, SiteRecord } from "@/types";
import { toJson, toRequest, type DashboardForm } from "@/lib/dashboardForm";
import {
  computeBalance,
  invariantViolations,
  reliabilityModel,
  seasonalCells,
  storageModel,
  summarizeSeasonal,
  type BalanceResult,
  type DemandResult,
  type ReliabilityResult,
  type SeasonalResult,
  type StorageModel,
} from "@/lib/derive";

export interface DerivedDashboard {
  site: SiteRecord;
  storage: StorageModel;
  balance: BalanceResult;
  reliability: ReliabilityResult;
}

const DEFAULT_REGION = "SA1";

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
 * forecast run, the regional demand model, and the deterministic derived
 * models that consume them.
 * In-flight requests are cancelled so a stale response can never overwrite a
 * newer one.
 */
export function useDashboard() {
  const [sites, setSites] = useState<SiteRecord[]>([]);
  const [regions, setRegions] = useState<RegionRecord[]>([]);
  const [regionId, setRegionId] = useState<string>(DEFAULT_REGION);
  const [regionError, setRegionError] = useState<string | null>(null);
  const [demandState, setDemandState] = useState<{
    key: string | null;
    data: DemandResult | null;
    error: string | null;
  }>({ key: null, data: null, error: null });
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

  useEffect(() => {
    const ctrl = new AbortController();
    listRegions(ctrl.signal)
      .then((list) => {
        setRegions(list);
        setRegionId((id) => (list.some((r) => r.region_id === id) ? id : (list[0]?.region_id ?? id)));
      })
      .catch((e: unknown) => {
        if (!isAbortError(e)) setRegionError("Could not load the regional registry.");
      });
    return () => ctrl.abort();
  }, []);

  const region = useMemo(
    () => regions.find((r) => r.region_id === regionId) ?? regions[0] ?? null,
    [regions, regionId]
  );

  // Demand follows the selected region and horizon (not the site selection).
  // State is keyed by request so loading is derived, never set synchronously.
  useEffect(() => {
    if (!region) return;
    const ctrl = new AbortController();
    const key = `${region.region_id}:${form.horizon_h}`;
    demandForRegion(region, form.horizon_h, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setDemandState({ key, data, error: null });
      })
      .catch((e: unknown) => {
        if (!isAbortError(e)) {
          setDemandState((s) => ({
            key,
            data: s.data,
            error: e instanceof Error ? e.message : "Regional demand unavailable.",
          }));
        }
      });
    return () => ctrl.abort();
  }, [region, form.horizon_h]);

  const demandKey = region ? `${region.region_id}:${form.horizon_h}` : null;
  const demandCurrent = demandState.key === demandKey ? demandState : null;
  const demand = demandCurrent?.data ?? null;
  const demandError = demandCurrent?.error ?? regionError;
  const demandLoading = !!region && !demandCurrent;

  // Seasonal comes from the backend, which mines it from three years of measured history -
  // metered demand and the fleet's actual output, with no model in front of it. The
  // client-side climatology stays as the fallback so the console still works offline.
  //
  // Result and the region it belongs to are stored together: keeping them apart would force
  // a synchronous clear inside the effect on every region change, which cascades renders.
  const [seasonalState, setSeasonalState] = useState<{
    key: string;
    data: SeasonalResult | null;
  } | null>(null);

  useEffect(() => {
    if (!region) return;
    const key = region.region_id;
    const ctrl = new AbortController();
    let live = true;
    seasonalForRegion(region, ctrl.signal)
      .then((resp) => live && setSeasonalState({ key, data: summarizeSeasonal(resp) }))
      .catch((e: unknown) => {
        if (!live || isAbortError(e)) return;
        setSeasonalState({ key, data: summarizeSeasonal(seasonalCells(region)) });
      });
    return () => {
      live = false;
      ctrl.abort();
    };
  }, [region]);

  // `seasonalState && region &&` is load-bearing, not defensive noise. Optional chaining on
  // both sides made `undefined === undefined` true on the very first render - before either
  // had loaded - and the branch then dereferenced a null `seasonalState`. It compiled, and
  // it blanked the dashboard.
  const seasonal =
    seasonalState && region && seasonalState.key === region.region_id ? seasonalState.data : null;

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
    };
  }, [result, site]);

  const jsonPreview = useMemo(() => toJson(form), [form]);

  // Dev-only consistency check for the derived layer (spec: no silent bad numbers).
  useEffect(() => {
    if (!import.meta.env.DEV || !result || !derived) return;
    const violations = invariantViolations(result, derived.balance);
    if (violations.length) console.warn("[derive] invariant violations:", violations);
  }, [result, derived]);

  // `site` is added to their return rather than replacing it: panels that talk to the
  // backend directly - the regional balance - read the selected site's market region from
  // it, and recomputing that resolution logic in each panel would let the two drift.
  return {
    sites,
    site,
    regions,
    region,
    regionId,
    setRegionId,
    demand,
    demandLoading,
    demandError,
    seasonal,
    form,
    patch,
    run,
    pickSite,
    result,
    loading,
    error,
    derived,
    jsonPreview,
  };
}
