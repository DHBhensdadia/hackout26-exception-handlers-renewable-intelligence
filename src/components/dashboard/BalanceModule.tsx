import { useMemo } from "react";
import type { ForecastResponse, HourPoint } from "@/types";
import { Bars, MixBar, Sparkline } from "@/components/charts/MixChart";
import { hourLabel } from "@/components/charts/ForecastBandChart";
import { fmt } from "@/lib/format";

/** Build an hourly demand curve this site would see (mocked; deterministic). */
function hourlyDemand(points: HourPoint[], capacity: number): number[] {
  const profile = [62, 58, 55, 53, 52, 53, 56, 62, 70, 78, 86, 92, 95, 93, 90, 88, 90, 92, 88, 82, 74, 68, 64, 61];
  return points.map((_, i) => (profile[i % 24] / 100) * capacity * 0.8);
}

const fmt2 = (v: number) => fmt(v, 1);

/**
 * Module 2 — Generation · Demand · Storage balance.
 * Forecast (p50 band) vs expected demand vs storage headroom, per hour.
 */
export function BalanceModule({
  forecast,
  capacity,
}: {
  forecast: ForecastResponse;
  capacity: number;
}) {
  const demand = useMemo(() => hourlyDemand(forecast.points, capacity), [forecast, capacity]);

  const analysis = useMemo(() => {
    const n = forecast.points.length;
    let surplusHours = 0;
    let shortageHours = 0;
    let surplusEnergy = 0;
    let shortageEnergy = 0;
    let worstShortage: HourPoint | null = null;
    let worstShortageDeficit = 0;

    for (let i = 0; i < n; i++) {
      const p = forecast.points[i];
      const d = demand[i];
      const gen = p.p50_mw;
      const deficit = d - gen;
      const surplus = gen - d;
      if (surplus > 0) {
        surplusHours++;
        surplusEnergy += surplus;
      } else {
        shortageHours++;
        shortageEnergy -= deficit;
        if (deficit > worstShortageDeficit) {
          worstShortageDeficit = deficit;
          worstShortage = p;
        }
      }
    }

    return {
      surplusHours,
      shortageHours,
      surplusEnergy,
      shortageEnergy,
      worstShortage,
      worstShortageDeficit,
      n,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forecast, demand]);

  const verdict =
    analysis.surplusHours / Math.max(1, analysis.n) > 0.25
      ? { label: "Surplus risk — prefer charging storage", tone: "warn" as const }
      : analysis.shortageHours / Math.max(1, analysis.n) > 0.2
        ? { label: "Shortage risk — hold backup headroom", tone: "bad" as const }
        : { label: "Balanced — forecast covers expected demand", tone: "ok" as const };

  const mix = useMemo(() => {
    let solar = 0;
    let wind = 0;
    for (const p of forecast.points) {
      // Heuristic split: the mock only returns one tech per run, so the
      // portfolio mix is shown in the summary; here we keep a tech-aware mix.
      if (forecast.tech === "solar") solar += p.p50_mw; else wind += p.p50_mw;
    }
    return { solar, wind, total: solar + wind };
  }, [forecast]);

  // Effective charts:
  // 1. demand vs generation bars (last 24 hours representative slice)
  const repHours = Math.min(24, forecast.points.length);
  const demArr = demand.slice(0, repHours);
  const genArr = forecast.points.slice(0, repHours).map((p) => p.p50_mw);

  return (
    <div style={{ display: "grid", gap: "1.2rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: ".8rem", flexWrap: "wrap" }}>
        <span className={`pill pill--${verdict.tone}`} style={{ fontSize: ".85rem" }}>{verdict.label}</span>
        <span style={{ fontSize: ".78rem", color: "var(--text-secondary)" }}>{analysis.n} hours analysed</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
        {[
          { k: "Surplus hours", v: `${analysis.surplusHours} / ${analysis.n}`, tone: "var(--c-green)" },
          { k: "Shortage hours", v: `${analysis.shortageHours} / ${analysis.n}`, tone: "var(--c-red)" },
          { k: "Surplus energy (p50)", v: `${fmt2(analysis.surplusEnergy)} MWh`, tone: "var(--c-green)" },
          { k: "Shortage energy (p50)", v: `${fmt2(analysis.shortageEnergy)} MWh`, tone: "var(--c-red)" },
        ].map((m) => (
          <div key={m.k} className="card" style={{ padding: ".9rem 1rem", minHeight: "auto", gap: ".3rem" }}>
            <span style={{ fontSize: ".72rem", color: "var(--text-muted)", fontWeight: 600 }}>{m.k}</span>
            <span style={{ fontSize: "1.1rem", fontWeight: 700, fontFamily: "var(--font-display)", color: m.tone }}>{m.v}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: "1.2rem" }} className="balance-grid">
        <div className="panel2" style={{ border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: "1rem 1.1rem", background: "var(--bg-elevated)" }}>
          <div className="panel2__h" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Expected demand vs forecast generation — first {repHours} h</span>
            <span className="mono" style={{ fontSize: ".66rem", color: "var(--text-muted)" }}>p50 · MW</span>
          </div>
          <div style={{ position: "relative", paddingTop: "1rem" }}>
            <Bars data={demArr} height={150} color="rgba(255,255,255,.14)" labelFmt={(v) => v.toFixed(0)} />
            <div style={{ position: "absolute", top: 16, left: 0, right: 0, bottom: 0 }}>
              <Bars data={genArr} height={134} color="var(--accent)" labelFmt={(v) => v.toFixed(0)} />
            </div>
          </div>
          <div style={{ marginTop: ".6rem", display: "flex", gap: "1rem", fontSize: ".74rem", color: "var(--text-secondary)" }}>
            <span><span style={{ color: "var(--accent)" }}>■</span> forecast (p50)</span>
            <span><span style={{ color: "rgba(255,255,255,.45)" }}>■</span> expected demand</span>
          </div>
        </div>

        <div className="panel2" style={{ border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: "1rem 1.1rem", background: "var(--bg-elevated)" }}>
          <div className="panel2__h">Energy mix — {analysis.n} h</div>
          <MixBar solar={mix.solar} wind={mix.wind} total={mix.total} />
          <div style={{ marginTop: ".9rem", borderTop: "1px solid var(--hairline)", paddingTop: ".8rem" }}>
            <div style={{ fontSize: ".74rem", color: "var(--text-secondary)", marginBottom: ".4rem" }}>Worst deficit hour</div>
            {analysis.worstShortage ? (
              <div className="mono" style={{ fontSize: ".76rem", color: "var(--text-secondary)" }}>
                {hourLabel(analysis.worstShortage.valid_time_utc)} → p50 {fmt2(analysis.worstShortage.p50_mw)} MW vs demand {fmt2(demand[analysis.worstShortage.horizon_h - 1] ?? 0)} MW
                (gap {fmt2(analysis.worstShortageDeficit)} MW)
              </div>
            ) : (
              <div className="mono" style={{ fontSize: ".76rem", color: "var(--c-green)" }}>No deficit within horizon.</div>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.2rem" }} className="bal-2">
        <div className="panel2" style={{ border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: "1rem 1.1rem", background: "var(--bg-elevated)" }}>
          <div className="panel2__h">Forecast vs potential (clearsky)</div>
          <div style={{ display: "grid", gap: ".6rem", marginTop: ".6rem" }}>
            {[
              ["PD (%)", (forecast.points.reduce((a, p) => a + (p.clearsky_mw ? p.p50_mw / Math.max(p.clearsky_mw, 1) : 0), 0) / Math.max(1, forecast.points.length)), 100],
            ].map(([k, v, mx]) => (
              <div key={String(k)} style={{ display: "flex", alignItems: "center", gap: ".6rem" }}>
                <span style={{ width: 90, fontSize: ".72rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{k}</span>
                <div style={{ flex: 1, height: 8, borderRadius: 8, background: "var(--surface-2)", overflow: "hidden" }}>
                  <div style={{ width: `${Math.min(100, (Number(v) / Number(mx)) * 100)}%`, height: "100%", background: "var(--c-green)", borderRadius: 8 }} />
                </div>
                <span className="mono" style={{ fontSize: ".72rem", color: "var(--text)" }}>{(Number(v) * 100).toFixed(0)}%</span>
              </div>
            ))}
            <div style={{ fontSize: ".72rem", color: "var(--text-muted)", marginTop: ".2rem" }}>
              Share of clearsky potential actually expected — the "physically possible" reference frame for curtailment.
            </div>
          </div>
        </div>

        <div className="panel2" style={{ border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: "1rem 1.1rem", background: "var(--bg-elevated)" }}>
          <div className="panel2__h">p90 surplus shape — storage sizing</div>
          <div style={{ marginTop: ".6rem" }}>
            <Sparkline values={forecast.points.map((p) => p.p90_mw)} width={340} height={70} />
          </div>
          <div className="mono" style={{ fontSize: ".72rem", color: "var(--text-muted)", marginTop: ".4rem" }}>
            Sizing a battery against p50 overflows half the time. Use the p90 band for storage capacity — the width is the honest risk.
          </div>
        </div>
      </div>
    </div>
  );
}