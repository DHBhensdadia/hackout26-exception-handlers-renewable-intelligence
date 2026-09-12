import type { SiteRecord } from "@/types";
import type { DashboardForm } from "@/lib/dashboardForm";
import { fact } from "@/lib/format";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="cp__field">
      <div className="cp__label">
        <span className="cp__label-t">{label}</span>
        {hint && <span className="cp__hint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

/** Segmented switch — the in-window control from the reference console (`.cvseg`). */
function Seg<T extends string>({
  value,
  options,
  onChange,
  mono,
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
  mono?: boolean;
}) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));
  return (
    <div
      className={mono ? "seg seg--mono" : "seg"}
      style={{ "--seg-n": options.length, "--seg-i": index } as React.CSSProperties}
    >
      <span className="seg__ind" aria-hidden="true" />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={o.value === value ? "on" : undefined}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const MODE_OPTIONS = [
  { value: "site", label: "Registered site" },
  { value: "cold", label: "Cold start" },
] as const;

const TECH_OPTIONS = [
  { value: "solar", label: "Solar" },
  { value: "wind", label: "Wind" },
] as const;

export function ControlsPanel({
  sites,
  form,
  onChange,
  onRun,
  loading,
}: {
  sites: SiteRecord[];
  form: DashboardForm;
  onChange: (patch: Partial<DashboardForm>) => void;
  onRun: () => void;
  loading: boolean;
}) {
  const selSite = sites.find((s) => s.site_id === form.site_id);

  return (
    <div className="code-card cp">
      <div className="code-card__bar">
        <span className="code-card__file">
          POST <span style={{ color: "#8fb3ff" }}>/forecast</span>
        </span>
        <span className="chip cp__tag">input</span>
      </div>

      <div className="cp__body">
        <section className="cp__group">
          <div className="cp__cap">Source</div>
          <Seg value={form.mode} options={MODE_OPTIONS} onChange={(mode) => onChange({ mode })} />
        </section>

        {form.mode === "site" ? (
          <section className="cp__group">
            <div className="cp__cap">Site</div>
            <Field label="Registered site" hint="GET /sites · registry">
              <div className="cp__select">
                <select
                  value={form.site_id}
                  onChange={(e) => {
                    const s = sites.find((x) => x.site_id === e.target.value);
                    if (s) onChange({ site_id: s.site_id, tech: s.tech, capacity_mw: s.capacity_mw });
                  }}
                >
                  {sites.map((s) => (
                    <option key={s.site_id} value={s.site_id}>
                      {s.site_id} · {s.tech} · {fact(s.capacity_mw)} MW
                    </option>
                  ))}
                </select>
                <span className="cp__select-chev" aria-hidden="true">▾</span>
              </div>
            </Field>
            {selSite && (
              <div className="cp__meta">
                <span>{selSite.name} · {selSite.region}</span>
                <span className="cp__meta-coord">
                  {selSite.latitude.toFixed(2)}, {selSite.longitude.toFixed(2)}
                </span>
                <span className={selSite.in_training_data ? "cp__flag cp__flag--ok" : "cp__flag cp__flag--warn"}>
                  {selSite.in_training_data ? "in training data" : "genuinely unseen"}
                </span>
              </div>
            )}
          </section>
        ) : (
          <>
            <section className="cp__group">
              <div className="cp__cap">Location</div>
              <div className="cp__row">
                <Field label="Latitude" hint="−90…90">
                  <input
                    className="cp__input"
                    type="number"
                    step="any"
                    value={form.latitude}
                    onChange={(e) => onChange({ latitude: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Longitude" hint="−180…180">
                  <input
                    className="cp__input"
                    type="number"
                    step="any"
                    value={form.longitude}
                    onChange={(e) => onChange({ longitude: Number(e.target.value) })}
                  />
                </Field>
              </div>
            </section>

            <section className="cp__group">
              <div className="cp__cap">Plant</div>
              <div className="cp__row">
                <Field label="Technology" hint="quantile pair">
                  <Seg mono value={form.tech} options={TECH_OPTIONS} onChange={(tech) => onChange({ tech })} />
                </Field>
                <Field label="Capacity (MW)" hint="> 0">
                  <input
                    className="cp__input"
                    type="number"
                    min={0.1}
                    step="any"
                    value={form.capacity_mw}
                    onChange={(e) => onChange({ capacity_mw: Number(e.target.value) })}
                  />
                </Field>
              </div>
            </section>

            <details className="cp__adv">
              <summary>Advanced site parameters</summary>
              <div className="cp__row cp__row--3">
                <Field label="tilt_deg" hint="min(lat,40)">
                  <input
                    className="cp__input"
                    type="number"
                    step="any"
                    value={form.tilt_deg ?? ""}
                    onChange={(e) => onChange({ tilt_deg: e.target.value === "" ? undefined : Number(e.target.value) })}
                  />
                </Field>
                <Field label="azimuth_deg" hint="default 180">
                  <input
                    className="cp__input"
                    type="number"
                    step="any"
                    value={form.azimuth_deg ?? ""}
                    onChange={(e) => onChange({ azimuth_deg: e.target.value === "" ? undefined : Number(e.target.value) })}
                  />
                </Field>
                <Field label="hub_height_m" hint="default 100">
                  <input
                    className="cp__input"
                    type="number"
                    step="any"
                    value={form.hub_height_m ?? ""}
                    onChange={(e) => onChange({ hub_height_m: e.target.value === "" ? undefined : Number(e.target.value) })}
                  />
                </Field>
              </div>
            </details>
          </>
        )}

        <section className="cp__group">
          <div className="cp__cap">Horizon</div>
          <Field label="Forecast horizon" hint="int 1–72 · default 72">
            <input
              className="cp__range"
              type="range"
              min={1}
              max={72}
              value={form.horizon_h}
              onChange={(e) => onChange({ horizon_h: Number(e.target.value) })}
            />
            <div className="cp__ticks">
              <span>1 h</span>
              <span className="cp__ticks-mid">{form.horizon_h} h</span>
              <span>72 h</span>
            </div>
          </Field>
        </section>

        <button className="btn cp__run" onClick={onRun} disabled={loading}>
          {loading ? "Running forecast…" : "Run forecast"}
        </button>
      </div>
    </div>
  );
}
