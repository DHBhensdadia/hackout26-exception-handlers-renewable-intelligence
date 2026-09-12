import { useCallback, useEffect, useMemo, useState } from "react";
import { SiteHeader } from "../components/SiteNav";
import { SiteFooter } from "../components/SiteFooter";
import { listSites, forecast } from "../api/client";
import type { ForecastResponse, SiteRecord } from "../types";
import { config } from "../config";
import { ControlsPanel, toJson, toRequest, type DashboardForm } from "../components/dashboard/ControlsPanel";
import { RunStatus, StatsRow } from "../components/dashboard/RunSummary";
import { ForecastBandChart } from "../components/charts/ForecastBandChart";
import { BalanceModule } from "../components/dashboard/BalanceModule";
import { SitesTable } from "../components/dashboard/SitesTable";
import { ForecastTable } from "../components/dashboard/ForecastTable";

type Tab = "forecast" | "balance" | "sites";

export default function Dashboard() {
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
  const [tab, setTab] = useState<Tab>("forecast");

  // Load the site registry once
  useEffect(() => {
    let active = true;
    listSites()
      .then((s) => {
        if (!active) return;
        setSites(s);
        const first = s.find((x) => x.site_id === form.site_id);
        if (first && first.tech !== form.tech) {
          setForm((f) => ({ ...f, tech: first.tech, capacity_mw: first.capacity_mw }));
        }
      })
      .catch(() => {
        if (active) setError("Could not load the site registry.");
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    const req = toRequest(form);
    forecast(req)
      .then((res) => {
        setResult(res);
        setTab((t) => (t === "sites" ? "forecast" : t));
      })
      .catch((e: Error) => {
        setError(e.message || "Forecast failed.");
      })
      .finally(() => setLoading(false));
  }, [form]);

  // Run once on mount so the dashboard is never blank.
  useEffect(() => {
    if (sites.length) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sites.length]);

  const patch = useCallback((p: Partial<DashboardForm>) => {
    setForm((f) => ({ ...f, ...p }));
  }, []);

  const pickSite = useCallback(
    (s: SiteRecord) => {
      patch({ mode: "site", site_id: s.site_id, tech: s.tech, capacity_mw: s.capacity_mw });
      // auto-run after a short tick so the new site's forecast loads
      setTimeout(() => {
        setLoading(true);
        setError(null);
        forecast(toRequest({
          mode: "site",
          site_id: s.site_id,
          tech: s.tech,
          capacity_mw: s.capacity_mw,
          latitude: s.latitude,
          longitude: s.longitude,
          horizon_h: form.horizon_h,
        }))
          .then(setResult)
          .catch((e: Error) => setError(e.message))
          .finally(() => setLoading(false));
      }, 0);
    },
    [form.horizon_h, patch]
  );

  const jsonPreview = useMemo(() => toJson(form), [form]);

  const warranty = result
    ? `p10 ≤ p50 ≤ p90 guaranteed · all values in [0, ${result.capacity_mw} MW] · solar forced to 0 at night (when applicable) · 80 % conformal calibration applied`
    : "Run a forecast to see the calibrated quantile output and operational analysis.";

  return (
    <>
      <SiteHeader />
      <div style={{ paddingTop: "96px", minHeight: "100vh" }} className="dashboard-shell">
        <div className="wrap">
          {/* ---------- Header ---------- */}
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: "1rem", marginBottom: "1.2rem" }}>
            <div>
              <span className="eyebrow">Decision support</span>
              <h1 className="h2" style={{ marginTop: ".5rem" }}>
                Forecast explorer
              </h1>
              <p className="lead" style={{ fontSize: "1rem", maxWidth: "62ch", marginTop: ".35rem" }}>
                24–72 hour solar &amp; wind forecast from the <span className="mono" style={{ color: "var(--accent)" }}>xgb-q-0.1.0</span> quantile models — p10 / p50 / p90, clearsky and physics per hour.
              </p>
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: ".5rem" }}>
              <button className="btn" onClick={run} disabled={loading}>
                {loading ? "Running forecast…" : "Run forecast"}
              </button>
              <RunStatus forecast={result} />
            </div>
          </div>

          {error && (
            <div style={{ padding: ".8rem 1rem", border: "1px solid rgba(235,94,87,.5)", background: "rgba(235,94,87,.08)", borderRadius: "var(--r-md)", color: "var(--c-red)", fontFamily: "var(--font-mono)", fontSize: ".86rem", marginBottom: "1rem" }}>
              {error}
            </div>
          )}

          {/* ---------- Tabs ---------- */}
          <div style={{ display: "flex", gap: 2, borderBottom: "1px solid var(--hairline)", marginBottom: "1.4rem" }}>
            {(
              [
                ["forecast", "Forecast"],
                ["balance", "Balance"],
                ["sites", "Site registry"],
              ] as [Tab, string][]
            ).map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                style={{
                  background: "none",
                  border: 0,
                  borderBottom: tab === id ? "2px solid var(--accent)" : "2px solid transparent",
                  color: tab === id ? "var(--text)" : "var(--text-muted)",
                  fontFamily: "var(--font-nav)",
                  fontSize: ".9rem",
                  fontWeight: 600,
                  padding: ".5rem 1.2rem .7rem",
                  cursor: "pointer",
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* ---------- Body ---------- */}
          {tab === "forecast" && (
            <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: "1.4rem", alignItems: "start" }} className="dash-main">
              {/* Controls */}
              <div style={{ position: "sticky", top: "16px" }}>
                <ControlsPanel
                  sites={sites}
                  form={form}
                  onChange={patch}
                  onRun={run}
                  loading={loading}
                />
                <div className="code-card" style={{ marginTop: "1rem", borderColor: "var(--hairline-strong)" }}>
                  <div className="code-card__bar">
                    <span className="code-card__file">request · preview</span>
                  </div>
                  <div className="code-card__body" style={{ maxHeight: "220px", overflow: "auto" }}>
                    <pre>{jsonPreview}</pre>
                  </div>
                </div>
              </div>

              {/* Output */}
              <div style={{ display: "grid", gap: "1.2rem", minWidth: 0 }}>
                {result ? (
                  <>
                    <StatsRow forecast={result} />
                    <div className="panel2" style={{ border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: "1.1rem 1.2rem", background: "var(--bg-elevated)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: ".6rem", marginBottom: ".6rem" }}>
                        <span style={{ color: "var(--text-secondary)", fontSize: ".86rem", fontWeight: 600 }}>
                          {result.tech === "solar" ? "Solar" : "Wind"} forecast — {result.points.length} h · {result.capacity_mw} MW
                        </span>
                        <span className="mono" style={{ fontSize: ".68rem", color: "var(--text-muted)" }}>issue {new Date(result.issue_time_utc).toUTCString()}</span>
                      </div>
                      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", fontSize: ".72rem", fontFamily: "var(--font-mono)", color: "var(--text-muted)", marginBottom: "1rem" }}>
                        <span><span style={{ color: "var(--accent-2)" }}>━━</span> p50 median</span>
                        <span><span style={{ color: "var(--text-muted)" }}>┄</span> p10/p90</span>
                        <span><span style={{ color: "var(--c-amber)" }}>┄</span> clearsky</span>
                        <span><span style={{ color: "var(--c-blue)" }}>∙∙</span> physics</span>
                        <span><span style={{ color: "var(--hairline-strong)" }}>┄</span> capacity cap</span>
                      </div>
                      <ForecastBandChart points={result.points} capacity={result.capacity_mw} />
                    </div>

                    <div className="panel2" style={{ border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: "1.1rem 1.2rem", background: "var(--bg-elevated)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: ".6rem" }}>
                        <span style={{ color: "var(--text-secondary)", fontSize: ".86rem", fontWeight: 600 }}>Hourly table — sorted, sortable</span>
                        <span className="mono" style={{ fontSize: ".68rem", color: "var(--text-muted)" }}>{result.points.length} rows · click a column to sort</span>
                      </div>
                      <ForecastTable forecast={result} />
                    </div>
                  </>
                ) : (
                  <div style={{ padding: "3rem 2rem", border: "1px dashed var(--hairline-strong)", borderRadius: "var(--r-md)", color: "var(--text-muted)", textAlign: "center" }}>
                    {loading ? "Running quantile forecast models…" : "Configure inputs and run a forecast."}
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === "balance" && result && (
            <BalanceModule forecast={result} capacity={result.capacity_mw} />
          )}
          {tab === "balance" && !result && (
            <div style={{ padding: "2rem", color: "var(--text-muted)" }}>Run a forecast first.</div>
          )}

          {tab === "sites" && (
            <SitesTable sites={sites} onPick={pickSite} activeId={result?.site_id ?? null} />
          )}

          {/* ---------- Integrity footer ---------- */}
          {result && (
            <div style={{ marginTop: "2.4rem", borderTop: "1px solid var(--hairline)", paddingTop: "1.2rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
                <div className="mono" style={{ fontSize: ".72rem", color: "var(--text-muted)" }}>
                  <div><b style={{ color: "var(--text-secondary)" }}>model_version</b> {result.model_version}</div>
                  <div><b style={{ color: "var(--text-secondary)" }}>weather_source</b> {result.weather_source}</div>
                  <div><b style={{ color: "var(--text-secondary)" }}>location_is_estimated</b> {String(result.location_is_estimated)}</div>
                  <div><b style={{ color: "var(--text-secondary)" }}>issue_time_utc</b> {result.issue_time_utc}</div>
                </div>
                <div className="mono" style={{ fontSize: ".72rem", color: "var(--text-muted)", maxWidth: "38ch" }}>
                  {warranty}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      <SiteFooter />
    </>
  );
}