import type { ForecastResponse, SiteRecord } from "@/types";
import { hourLabel } from "@/lib/derive";
import { useActiveSection } from "@/hooks/useActiveSection";
import { ControlsPanel, type DashboardForm } from "./ControlsPanel";
import { SECTIONS } from "./sections";

/**
 * The sticky run rail: provenance, the single run control (POST /forecast),
 * the § index, and the request preview. Replaces the old tab bar.
 */
export function RunRail({
  sites,
  form,
  patch,
  run,
  loading,
  result,
  site,
  jsonPreview,
}: {
  sites: SiteRecord[];
  form: DashboardForm;
  patch: (p: Partial<DashboardForm>) => void;
  run: () => void;
  loading: boolean;
  result: ForecastResponse | null;
  site: SiteRecord | null;
  jsonPreview: string;
}) {
  const active = useActiveSection(SECTIONS.map((s) => s.id));

  return (
    <aside className="rail">
      <div className="rail__prov">
        <div className="rail__prov-head">
          <span className={`rail__dot${result ? " rail__dot--on" : ""}`} />
          <span>{result ? "run loaded" : "awaiting run"}</span>
        </div>

        {result ? (
          <dl className="rail__dl">
            <div>
              <dt>site</dt>
              <dd>{result.site_id}</dd>
            </div>
            {site && (
              <div>
                <dt>name</dt>
                <dd>
                  {site.name} · {site.region}
                </dd>
              </div>
            )}
            <div>
              <dt>issued</dt>
              <dd>{hourLabel(result.issue_time_utc)}</dd>
            </div>
            <div>
              <dt>model</dt>
              <dd>{result.model_version}</dd>
            </div>
            <div>
              <dt>weather</dt>
              <dd>{result.weather_source}</dd>
            </div>
          </dl>
        ) : (
          <p className="rail__idle">Configure inputs and run a forecast.</p>
        )}

        <div className="rail__tags">
          <span className="tag tag--ok">calibrated 80 %</span>
          {result?.location_is_estimated && <span className="tag tag--warn">location estimated</span>}
        </div>
      </div>

      <ControlsPanel sites={sites} form={form} onChange={patch} onRun={run} loading={loading} />

      <nav className="rail__index" aria-label="Sections">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className={active === s.id ? "on" : undefined}>
            <span className="n">§{s.n}</span>
            {s.label}
          </a>
        ))}
      </nav>

      <details className="rail__json">
        <summary>Request preview</summary>
        <pre>{jsonPreview}</pre>
      </details>
    </aside>
  );
}
