import type { ColdStartForecastRequest, ForecastRequest, SiteForecastRequest, SiteRecord, Tech } from "@/types";
import { fact } from "@/lib/format";

export interface DashboardForm {
  mode: "site" | "cold";
  site_id: string;
  tech: Tech;
  capacity_mw: number;
  latitude: number;
  longitude: number;
  horizon_h: number;
  tilt_deg?: number;
  azimuth_deg?: number;
  hub_height_m?: number;
}

/** Collapse an input form into a POST /forecast request. */
export function toRequest(form: DashboardForm): ForecastRequest & { capacity_mw: number; tech: Tech } {
  const base = { horizon_h: form.horizon_h, capacity_mw: form.capacity_mw, tech: form.tech };
  if (form.mode === "site") {
    return { site_id: form.site_id, ...base } as SiteForecastRequest & { capacity_mw: number; tech: Tech };
  }
  const cold: ColdStartForecastRequest = {
    latitude: form.latitude,
    longitude: form.longitude,
    tech: form.tech,
    capacity_mw: form.capacity_mw,
    horizon_h: form.horizon_h,
    tilt_deg: form.tilt_deg,
    azimuth_deg: form.azimuth_deg,
    hub_height_m: form.hub_height_m,
  };
  return cold as ForecastRequest & { capacity_mw: number; tech: Tech };
}

/** Compose the JSON preview box for the request panel. */
export function toJson(view: DashboardForm): string {
  const req = toRequest(view);
  return JSON.stringify(req, null, 2);
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label style={{ display: "grid", gap: ".35rem" }}>
      <span style={{ fontSize: ".78rem", fontWeight: 600, color: "var(--text-secondary)" }}>{label}</span>
      {children}
      {hint && <span style={{ fontSize: ".68rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{hint}</span>}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--bg-elevated)",
  border: "1px solid var(--hairline-strong)",
  color: "var(--text)",
  padding: ".6rem .8rem",
  borderRadius: "var(--r-sm)",
  fontFamily: "var(--font-body)",
  fontSize: ".95rem",
};

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
  const mode = form.mode;
  const setMode = (m: "site" | "cold") => onChange({ mode: m });

  const selSite = sites.find((s) => s.site_id === form.site_id);

  return (
    <div className="code-card" style={{ borderColor: "var(--hairline-strong)" }}>
      <div className="code-card__bar">
        <span className="code-card__file">
          POST <span style={{ color: "#8fb3ff" }}>/forecast</span>
        </span>
        <span className="chip" style={{ background: "transparent", border: "1px solid var(--hairline-strong)", color: "var(--text-muted)" }}>
          input
        </span>
      </div>
      <div style={{ padding: "1.1rem 1.2rem", display: "grid", gap: "1rem" }}>
        {/* mode selector */}
        <div style={{ display: "inline-flex", gap: 2, background: "var(--surface-2)", border: "1px solid var(--hairline)", borderRadius: "var(--r-pill)", padding: 3, alignSelf: "flex-start" }}>
          {(["site", "cold"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                fontFamily: "var(--font-body)",
                fontSize: ".78rem",
                fontWeight: 600,
                color: mode === m ? "#08090a" : "var(--text-muted)",
                background: mode === m ? "var(--text)" : "transparent",
                border: 0,
                padding: ".3rem .85rem",
                borderRadius: "var(--r-pill)",
                cursor: "pointer",
              }}
            >
              {m === "site" ? "Registered site" : "Cold start (lat/lon)"}
            </button>
          ))}
        </div>

        {mode === "site" ? (
          <Field label="Site" hint="GET /sites · registry">
            <select
              value={form.site_id}
              onChange={(e) => {
                const s = sites.find((x) => x.site_id === e.target.value);
                if (s) onChange({ site_id: s.site_id, tech: s.tech, capacity_mw: s.capacity_mw });
              }}
              style={inputStyle}
            >
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>
                  {s.site_id} · {s.tech} · {fact(s.capacity_mw)} MW
                </option>
              ))}
            </select>
            {selSite && (
              <span style={{ fontSize: ".72rem", color: "var(--text-muted)" }}>
                {selSite.name} · {selSite.region} · {selSite.latitude.toFixed(2)}, {selSite.longitude.toFixed(2)}
                {" · "}
                {selSite.in_training_data ? (
                  <span style={{ color: "var(--c-green)" }}>in training data</span>
                ) : (
                  <span style={{ color: "var(--c-amber)" }}>genuinely unseen</span>
                )}
              </span>
            )}
          </Field>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".9rem" }}>
              <Field label="Latitude" hint="−90…90">
                <input
                  type="number"
                  step="any"
                  value={form.latitude}
                  onChange={(e) => onChange({ latitude: Number(e.target.value) })}
                  style={inputStyle}
                />
              </Field>
              <Field label="Longitude" hint="−180…180">
                <input
                  type="number"
                  step="any"
                  value={form.longitude}
                  onChange={(e) => onChange({ longitude: Number(e.target.value) })}
                  style={inputStyle}
                />
              </Field>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".9rem" }}>
              <Field label="Technology" hint="selects 3-quantile model pair">
                <div style={{ display: "inline-flex", gap: 2, background: "var(--surface-2)", border: "1px solid var(--hairline)", borderRadius: "var(--r-pill)", padding: 3 }}>
                  {(["solar", "wind"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => onChange({ tech: t })}
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: ".74rem",
                        fontWeight: 600,
                        color: form.tech === t ? "#08090a" : "var(--text-muted)",
                        background: form.tech === t ? "var(--text)" : "transparent",
                        border: 0,
                        padding: ".28rem .8rem",
                        borderRadius: "var(--r-pill)",
                        cursor: "pointer",
                        textTransform: "uppercase",
                        letterSpacing: ".03em",
                      }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Capacity (MW)" hint="> 0">
                <input
                  type="number"
                  min={0.1}
                  step="any"
                  value={form.capacity_mw}
                  onChange={(e) => onChange({ capacity_mw: Number(e.target.value) })}
                  style={inputStyle}
                />
              </Field>
            </div>
            <details>
              <summary style={{ cursor: "pointer", fontSize: ".82rem", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                Advanced site parameters
              </summary>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: ".9rem", marginTop: ".9rem" }}>
                <Field label="tilt_deg" hint="default min(lat,40)">
                  <input type="number" step="any" value={form.tilt_deg ?? ""} onChange={(e) => onChange({ tilt_deg: e.target.value === "" ? undefined : Number(e.target.value) })} style={inputStyle} />
                </Field>
                <Field label="azimuth_deg" hint="default 180">
                  <input type="number" step="any" value={form.azimuth_deg ?? ""} onChange={(e) => onChange({ azimuth_deg: e.target.value === "" ? undefined : Number(e.target.value) })} style={inputStyle} />
                </Field>
                <Field label="hub_height_m" hint="default 100">
                  <input type="number" step="any" value={form.hub_height_m ?? ""} onChange={(e) => onChange({ hub_height_m: e.target.value === "" ? undefined : Number(e.target.value) })} style={inputStyle} />
                </Field>
              </div>
            </details>
          </>
        )}

        {/* horizon slider */}
        <Field label={`Horizon — ${form.horizon_h} h`} hint="int 1–72 · default 72">
          <input
            type="range"
            min={1}
            max={72}
            value={form.horizon_h}
            onChange={(e) => onChange({ horizon_h: Number(e.target.value) })}
            style={{ width: "100%", accentColor: "var(--accent)" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: ".66rem", color: "var(--text-muted)" }}>
            <span>1 h</span>
            <span>{form.horizon_h} h</span>
            <span>72 h</span>
          </div>
        </Field>

        <button
          onClick={onRun}
          disabled={loading}
          className="btn"
          style={{ justifySelf: "start" }}
        >
          {loading ? "Running forecast…" : "Run forecast"}
        </button>
      </div>
    </div>
  );
}