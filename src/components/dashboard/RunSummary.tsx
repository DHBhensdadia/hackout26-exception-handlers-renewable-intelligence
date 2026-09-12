import { fact, formatMw } from "@/lib/format";
import type { ForecastResponse } from "@/types";

/** Header run status — mirrors the envelope fields of /forecast. */
export function RunStatus({ forecast }: { forecast: ForecastResponse | null }) {
  if (!forecast) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: ".5rem", fontFamily: "var(--font-mono)", fontSize: ".72rem", color: "var(--text-muted)" }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--text-muted)" }} />
        idle — awaiting run
      </span>
    );
  }
  const { model_version, weather_source, site_id, issue_time_utc, capacity_mw } = forecast;
  const d = new Date(issue_time_utc).toUTCString().slice(0, 22);
  return (
    <span
      style={{
        display: "inline-flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: "1rem",
        fontFamily: "var(--font-mono)",
        fontSize: ".72rem",
        color: "var(--text-muted)",
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: ".35rem" }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--c-green)" }} />
        {model_version}
      </span>
      <span>•</span>
      <span>{weather_source}</span>
      <span>•</span>
      <span>{site_id}</span>
      <span>•</span>
      <span>{capacity_mw} MW</span>
      <span>•</span>
      <span>issued {d}</span>
    </span>
  );
}

/** Stat tiles row — the headline numbers from the run. */
export function StatsRow({
  forecast,
  demand_met_p95,
  verdict,
}: {
  forecast: ForecastResponse;
  demand_met_p95?: number;
  verdict?: { label: string; tone: "ok" | "warn" | "bad" };
}) {
  const H = forecast.points.length;
  const p50Sum = forecast.points.reduce((a, p) => a + p.p50_mw, 0);
  const p10Sum = forecast.points.reduce((a, p) => a + p.p10_mw, 0);
  const p90Sum = forecast.points.reduce((a, p) => a + p.p90_mw, 0);
  const avg = H ? p50Sum / H : 0;

  const tiles = [
    { k: "Capacity", v: `${forecast.capacity_mw} MW`, note: "installed" },
    { k: "Horizon", v: `${H} h`, note: "of forecast" },
    { k: "Median energy", v: `${fact(p50Sum)} MWh`, note: "p50 over horizon" },
    { k: "80 % band", v: `${fact(p10Sum)}–${fact(p90Sum)} MWh`, note: "p10 · p90" },
    { k: "Avg output", v: `${formatMw(avg)}`, note: "mean p50 / h" },
  ];

  return (
    <>
      <div className="grid grid--5" style={{ gridTemplateColumns: "repeat(5,1fr)" }}>
        {tiles.map((t) => (
          <div key={t.k} className="card" style={{ padding: "1.1rem 1.2rem", gap: ".45rem", minHeight: "auto" }}>
            <span style={{ fontSize: ".74rem", letterSpacing: ".02em", fontWeight: 600, color: "var(--text-muted)" }}>{t.k}</span>
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: "1.5rem", letterSpacing: "-0.02em", color: "var(--text)" }}>{t.v}</span>
            <span style={{ fontSize: ".7rem", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>{t.note}</span>
          </div>
        ))}
      </div>

      {verdict && (
        <div style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: ".8rem", flexWrap: "wrap" }}>
          <span className={`pill pill--${verdict.tone === "ok" ? "ok" : verdict.tone === "warn" ? "warn" : "bad"}`} style={{ fontSize: ".85rem" }}>
            {verdict.label}
          </span>
          <span style={{ fontSize: ".8rem", color: "var(--text-secondary)" }}>
            {demand_met_p95 !== undefined ? `expected demand met in ${demand_met_p95.toFixed(0)}% of hours (p50)` : ""}
          </span>
        </div>
      )}
    </>
  );
}