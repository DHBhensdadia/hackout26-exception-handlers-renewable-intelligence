import type { ForecastResponse } from "@/types";
import type { DerivedDashboard } from "@/hooks/useDashboard";
import { fact } from "@/lib/format";
import { hourLabel } from "@/lib/derive";
import { Cell, CellGrid } from "../ui/CellGrid";

interface Alert {
  tone: "ok" | "warn" | "bad";
  label: string;
  body: string;
}

/** §01 — the decision first: what to do, why, and the numbers behind it. */
export function DecisionCallout({ forecast, derived }: { forecast: ForecastResponse; derived: DerivedDashboard }) {
  const { balance, storage, reliability } = derived;

  const p50Sum = forecast.points.reduce((a, p) => a + p.p50_mw, 0);
  const p10Sum = forecast.points.reduce((a, p) => a + p.p10_mw, 0);
  const p90Sum = forecast.points.reduce((a, p) => a + p.p90_mw, 0);
  const peak = forecast.points.reduce((a, p) => (p.p50_mw > a.p50_mw ? p : a), forecast.points[0]);

  const alerts = [
    balance.worstShortage
      ? {
          tone: "bad" as const,
          label: "Worst deficit",
          body: `${hourLabel(balance.worstShortage.valid_time_utc)} · ${Math.abs(balance.worstShortage.net).toFixed(1)} MW below demand`,
        }
      : null,
    balance.worstSurplus
      ? {
          tone: "warn" as const,
          label: "Surplus window",
          body: `${hourLabel(balance.worstSurplus.valid_time_utc)} · ${balance.worstSurplus.net.toFixed(1)} MW above demand`,
        }
      : null,
    {
      // Not "equipment risk" - there is no model behind that. The quietest window is a
      // real, observable read: when taking the plant offline costs the least generation.
      tone: "ok" as const,
      label: "Maintenance window",
      body: reliability.maintenanceWindow
        ? `${reliability.maintenanceWindow.start} · ${reliability.windowLossMwh} MWh forgone`
        : "no quiet window inside the horizon",
    },
    {
      tone: "ok" as const,
      label: "Storage headroom",
      body: `${storage.headroom_mwh} MWh free · ${storage.soc_pct} % charged`,
    },
  ].filter((a): a is Alert => a !== null).slice(0, 3);

  return (
    <>
      <div className="call">
        <div className={`call__verdict call__verdict--${balance.verdict.tone}`}>
          <span className="call__key">{balance.verdict.key}</span>
          <h3 className="call__label">{balance.verdict.label}</h3>
          <p className="call__action">{balance.verdict.action}</p>
          <p className="call__detail">{balance.verdict.detail}</p>
        </div>
        <ol className="call__alerts">
          {alerts.map((a) => (
            <li key={a.label} className={`call__alert call__alert--${a.tone}`}>
              <span className="call__alert-label">{a.label}</span>
              <span className="call__alert-body">{a.body}</span>
            </li>
          ))}
        </ol>
      </div>

      <CellGrid columns={5} className="call__kpis">
        <Cell k="Median energy" v={`${fact(p50Sum)} MWh`} note="p50 over horizon" />
        <Cell k="80 % band" v={`${fact(p10Sum)}–${fact(p90Sum)}`} note="p10 · p90 MWh" />
        <Cell k="Peak hour" v={`${peak.p50_mw.toFixed(1)} MW`} note={hourLabel(peak.valid_time_utc)} />
        <Cell k="Demand met" v={`${balance.demandMetPct} %`} note="hours covered at p50" accent="var(--c-green)" />
        <Cell k="Storage" v={`${storage.capacity_mwh} MWh`} note={`${storage.power_mw} MW · ${storage.soc_pct} % charged`} />
      </CellGrid>
    </>
  );
}
